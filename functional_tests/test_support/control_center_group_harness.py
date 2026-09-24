# control_center_group_harness.py
"""An isolated harness for the Control Center's group-document writers.

Version: 0.261.160
Implemented in: 0.261.160

It builds on ``group_directory_harness``, which it imports and does not change, and
takes from it the etag-enforcing groups container, the people, the group document
factory, the real ``functions_group`` (whose ``update_group_document_with_etag_guard``
every writer here now uses), the bootstrap cache bump recorder, the activity logs
container and the ``functions_activity_logging`` recorder.

Run unchanged from their source:

- from ``route_backend_control_center``: ``enhance_group_with_activity``,
  ``_GroupChangeAnswer`` and the ownership answers at module level, and, from inside
  ``register_route_backend_control_center``, the group status and add-member routes
  with their real decorators, ``_execute_approved_action``, ``_execute_take_ownership``
  and ``_execute_transfer_ownership``;
- ``login_required`` and ``control_center_required`` from ``functions_authentication``;
- ``mark_approval_executed`` from ``functions_approvals``, over an approvals container.

Replaced: the group documents container, which models exactly the queries
``enhance_group_with_activity`` sends and refuses any other, and ``debug_print``. The
extracted code runs in one namespace; a name it uses that this harness doesn't
provide fails with a ``NameError`` where it's used.
"""

import ast
import copy
import logging
import typing
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from types import SimpleNamespace

from flask import Blueprint, Flask, jsonify, request, session

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, execute_functions
from test_support.group_directory_harness import group_directory_environment


SOURCE = "route_backend_control_center.py"
MODULE_LEVEL = {"enhance_group_with_activity", "_GroupChangeAnswer",
                "GROUP_OWNERSHIP_CHANGED_MESSAGE", "GROUP_NO_LONGER_EXISTS_MESSAGE",
                "GROUP_APPROVAL_CONFLICT_MESSAGE"}
NESTED = {"api_update_group_status", "api_admin_add_group_member", "_execute_approved_action",
          "_execute_take_ownership", "_execute_transfer_ownership"}
CC_ADMIN = {"oid": "cc-admin", "roles": ["Admin"], "name": "Casey Control", "preferred_username": "cc.admin@example.test"}


def _normalized(query):
    return " ".join(str(query).split())


class GroupDocumentsMetricsContainer:
    """The group documents container, as the queries ``enhance_group_with_activity`` sends see it."""

    def __init__(self):
        self.records = []
        self.queries = []

    def query_items(self, query, parameters=None, enable_cross_partition_query=None, **kwargs):
        text = _normalized(query)
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        self.queries.append(text)
        rows = [record for record in self.records if record.get("group_id") == values.get("@group_id")]
        metadata = [record for record in rows if record.get("type") == "document_metadata"]
        if text == "SELECT VALUE COUNT(1) FROM c WHERE c.group_id = @group_id":
            return [len(rows)]
        if text == "SELECT VALUE COUNT(1) FROM c WHERE c.group_id = @group_id AND c.type = 'document_metadata'":
            return [len(metadata)]
        if text == "SELECT VALUE SUM(c.number_of_pages) FROM c WHERE c.group_id = @group_id AND c.type = 'document_metadata'":
            return [sum(record.get("number_of_pages", 0) for record in metadata)]
        if text == "SELECT c.upload_date, c.created_at, c.modified_at FROM c WHERE c.group_id = @group_id":
            return [{key: record[key] for key in ("upload_date", "created_at", "modified_at") if key in record}
                    for record in rows]
        if text == "SELECT VALUE COUNT(1) FROM c WHERE c.group_id = @group_id AND c.upload_date >= @week_ago":
            return [sum(1 for record in rows if str(record.get("upload_date", "")) >= values["@week_ago"])]
        raise AssertionError(f"enhance_group_with_activity sent a query this harness does not model: {text}")


def _extract(tree):
    """The selected module-level and nested definitions of the Control Center module, in source order."""
    selected, found = [], set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in MODULE_LEVEL:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in MODULE_LEVEL for target in node.targets
        ):
            selected.append(node)
            found.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_control_center":
            for inner in node.body:
                if isinstance(inner, ast.FunctionDef) and inner.name in NESTED:
                    selected.append(inner)
                    found.add(inner.name)
    missing = (MODULE_LEVEL | NESTED) - found
    assert not missing, f"Missing Control Center definitions: {missing}"
    return selected


def _approvals_namespace(approvals, env):
    """``mark_approval_executed`` and the approval constants, executed from functions_approvals."""
    tree = ast.parse((APP_ROOT / "functions_approvals.py").read_text(encoding="utf-8"))
    constants = [
        node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id.startswith(("TYPE_", "STATUS_")) for target in node.targets)
    ]
    namespace = {
        "Any": typing.Any, "Dict": typing.Dict, "Optional": typing.Optional,
        "cosmos_approvals_container": approvals, "datetime": datetime,
        "is_m365_approval": lambda approval: False,
        "log_event": env.log_event, "debug_print": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=constants, type_ignores=[]), "functions_approvals.py", "exec"), namespace)
    execute_functions("functions_approvals.py", {"mark_approval_executed"}, namespace)
    return namespace


@contextmanager
def control_center_group_environment():
    """The group directory environment, plus the Control Center group writers on their own app."""
    with group_directory_environment() as env:
        approvals = FakeContainer("cosmos_approvals_container", "group_id")
        documents = GroupDocumentsMetricsContainer()
        approvals_namespace = _approvals_namespace(approvals, env)

        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "get_settings": env.get_settings, "debug_print": lambda *args, **kwargs: None,
        }
        execute_functions("functions_authentication.py", {"login_required", "control_center_required"}, auth_namespace)

        blueprint = Blueprint("backend_control_center_groups", __name__)
        namespace = {
            "bp": blueprint,
            "swagger_route": lambda **kwargs: (lambda function: function),
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "login_required": auth_namespace["login_required"],
            "control_center_required": auth_namespace["control_center_required"],
            "request": request, "session": session, "jsonify": jsonify,
            "datetime": datetime, "timedelta": timedelta, "timezone": timezone, "uuid": uuid, "logging": logging,
            "cosmos_groups_container": env.groups,
            "cosmos_group_documents_container": documents,
            "cosmos_activity_logs_container": env.activity_logs,
            "update_group_document_with_etag_guard": env.modules.group.update_group_document_with_etag_guard,
            "GroupDocumentWriteConflict": env.modules.group.GroupDocumentWriteConflict,
            "GROUP_WRITE_CONFLICT_CODE": env.modules.group.GROUP_WRITE_CONFLICT_CODE,
            "GROUP_WRITE_CONFLICT_MESSAGE": env.modules.group.GROUP_WRITE_CONFLICT_MESSAGE,
            "log_event": env.log_event,
            "debug_print": lambda *args, **kwargs: None,
            "is_m365_approval": lambda approval: False,
            "mark_approval_executed": approvals_namespace["mark_approval_executed"],
            "TYPE_TAKE_OWNERSHIP": approvals_namespace["TYPE_TAKE_OWNERSHIP"],
            "TYPE_TRANSFER_OWNERSHIP": approvals_namespace["TYPE_TRANSFER_OWNERSHIP"],
            "TYPE_DELETE_DOCUMENTS": approvals_namespace["TYPE_DELETE_DOCUMENTS"],
            "TYPE_DELETE_GROUP": approvals_namespace["TYPE_DELETE_GROUP"],
            "TYPE_DELETE_USER_DOCUMENTS": approvals_namespace["TYPE_DELETE_USER_DOCUMENTS"],
            "TYPE_WARN_USER": approvals_namespace["TYPE_WARN_USER"],
            "TYPE_SUSPEND_USER": approvals_namespace["TYPE_SUSPEND_USER"],
            "TYPE_BLOCK_USER": approvals_namespace["TYPE_BLOCK_USER"],
            "CLIENTS": {},
            "storage_account_group_documents_container_name": "group-documents",
        }
        tree = ast.parse((APP_ROOT / SOURCE).read_text(encoding="utf-8"))
        exec(compile(ast.Module(body=_extract(tree), type_ignores=[]), SOURCE, "exec"), namespace)

        app = Flask("control_center_group_writers")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        app.register_blueprint(blueprint)
        client = app.test_client()

        def as_cc_admin(user=CC_ADMIN):
            with client.session_transaction() as state:
                state["user"] = copy.deepcopy(user)

        def approval(approval_id, request_type, group_id="group-1", metadata=None, requester="admin-1"):
            name, email = {"admin-1": ("Adam Admin", "adam.admin@example.test")}.get(
                requester, (f"Name {requester}", f"{requester}@example.test"))
            record = {
                "id": approval_id, "group_id": group_id, "request_type": request_type, "status": "approved",
                "requester_id": requester, "requester_email": email, "requester_name": name,
                "metadata": metadata or {},
            }
            approvals.seed(record)
            return approvals.get(approval_id, group_id)

        def reset():
            env.reset()
            approvals.records.clear()
            approvals.calls.clear()
            documents.records.clear()
            documents.queries.clear()
            env.settings.update({"enable_enhanced_citations": False, "require_member_of_control_center_admin": False})
            as_cc_admin()

        env.cc = SimpleNamespace(
            namespace=namespace, client=client, approvals=approvals, documents=documents,
            as_cc_admin=as_cc_admin, approval=approval, reset=reset, admin=CC_ADMIN,
        )
        reset()
        yield env
