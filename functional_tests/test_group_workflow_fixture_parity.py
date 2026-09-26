# test_group_workflow_fixture_parity.py
#!/usr/bin/env python3
"""
Functional test for group workflow fixture parity.
Version: 0.261.178
Implemented in: 0.261.178

This test holds the closed V2 browser fixtures' group workflow answers to the real
``/api/group/workflows`` route bodies for list, save, run, active-run cancellation and
delete. The route handlers, authorization helpers and route-level workflow helpers are
compiled from ``route_backend_workflows.py``; ``assert_group_role``,
``get_user_role_in_group`` and ``require_active_group`` are compiled from
``functions_group.py`` over an in-memory group record; and the group workflow settings
predicates are compiled from ``functions_settings.py``.

Only persistence, distributed locks, logging and durable runtime services are doubled.
Those doubles copy the real return contracts: ``queue_durable_workflow_run`` returns
``{success, run, workflow, runtime}`` before ``_queue_workflow_response`` narrows the run
to ``id``, ``workflow_id``, ``status``, ``success``, ``durable_execution``, ``started_at``
and ``completed_at`` (``functions_workflow_runtime.py`` lines 170-182), while
``cancel_durable_workflow_run`` returns ``{run, workflow}`` and
``_request_workflow_run_cancellation`` exposes only ``id``, ``workflow_id``, ``status``,
``durable_execution`` and ``runtime`` for durable cancellations
(``route_backend_workflows.py`` lines 124-127 and
``functions_workflow_runtime.py`` lines 326-333). Workflow save persistence is doubled;
the save payload is kept to the fields the V2 client reads in these fixtures, while route
authorization, status mapping and response envelopes stay real.
"""

import ast
import copy
import json
import logging
import sys
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import pytest
from flask import Blueprint, Flask, jsonify, request, session


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
ROUTES_FILE = APP_ROOT / "route_backend_workflows.py"
GROUP_FILE = APP_ROOT / "functions_group.py"
SETTINGS_FILE = APP_ROOT / "functions_settings.py"
ASSIGNMENT_IDS_FILE = APP_ROOT / "functions_group_assignment_ids.py"
POLICY_FILE = APP_ROOT / "functions_group_workflow_policy.py"

for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture  # noqa: E402
from ui_tests.fixtures.workflow_editor import GROUP_ID as EDITOR_GROUP_ID  # noqa: E402
from ui_tests.fixtures.workflow_editor import WorkflowEditorFixture  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN  # noqa: E402


SHELL_GROUP_ID = "group-a"
SHELL_WORKFLOW_ID = "workflow-1"
EDITOR_WORKFLOW_ID = "group-workflow"
ROLE_USERS = {
    "Owner": "owner-user",
    "Admin": "admin-user",
    "DocumentManager": "manager-user",
    "User": "member-user",
}
ROUTE_HELPERS = (
    "_normalize_identifier",
    "_workflow_definition_response",
    "_queue_workflow_response",
    "_request_workflow_run_cancellation",
    "_assert_group_workflow_feature_enabled",
    "_resolve_active_group_for_workflows",
    "_resolve_group_workflow_request_group",
    "_resolve_active_group_for_workflow_management",
)
ROUTE_CLASSES = ("WorkflowCancellationConflictError",)
ROUTE_FUNCTIONS = (
    "get_group_workflows_route",
    "save_group_workflow_route",
    "delete_group_workflow_route",
    "cancel_active_group_workflow_run",
    "run_group_workflow_route",
)


def _module_constant(source_file, name):
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"), filename=str(source_file))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a literal constant in {source_file.name}")


def _nodes(source_file, names):
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"), filename=str(source_file))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names and node.name not in found:
            node.decorator_list = []
            found[node.name] = node
    missing = set(names) - set(found)
    assert not missing, f"Missing definitions in {source_file.name}: {sorted(missing)}"
    return [found[name] for name in names]


def _compile_into(source_file, names, namespace):
    module = ast.Module(body=_nodes(source_file, names), type_ignores=[])
    exec(compile(module, str(source_file), "exec"), namespace)
    return namespace


def _load_pure_module(name, source_file):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, source_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GROUP_WORKFLOW_MEMBER_ROLES = _module_constant(POLICY_FILE, "GROUP_WORKFLOW_MEMBER_ROLES")


class _FakeContext:
    def route(self, *args, **kwargs):
        pass

    def on(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self, url=f"{ORIGIN}/v2/groups/{SHELL_GROUP_ID}/workflows"):
        self.context = _FakeContext()
        self.url = url

    def on(self, *args, **kwargs):
        pass


class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    def __init__(self, path):
        self.request = _FakeRequest(f"{ORIGIN}{path}")
        self.status = None
        self.payload = None

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json


def _session_guard():
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not session.get("user"):
                return jsonify({"error": "Authentication required."}), 401
            return function(*args, **kwargs)
        return wrapped
    return decorate


def _round_trip(payload):
    return json.loads(json.dumps(payload))


def _workflow(workflow_id, group_id, **updates):
    record = {
        "id": workflow_id,
        "group_id": group_id,
        "user_id": "owner-user",
        "name": "Review group files" if workflow_id == SHELL_WORKFLOW_ID else "Group review workflow",
        "description": "Review approved sources.",
        "definition_version": 2,
        "definition_revision": f"revision:{workflow_id}:1",
        "runner_type": "model",
        "trigger_type": "manual",
        "status": "idle",
        "active_run_id": "",
        "durable_execution": True,
        "tasks": [{"id": "task-a", "name": "Collect evidence", "instructions": "Collect evidence."}],
        "task_prompt": "Summarize the selected files.",
    }
    record.update(copy.deepcopy(updates))
    return record


def _save_payload(workflow_id, group_id):
    return {
        "id": "",
        "group_id": group_id,
        "definition_version": 2,
        "name": "New group workflow",
        "description": "Created by parity test.",
        "runner_type": "model",
        "trigger_type": "manual",
        "task_prompt": "Summarize updates.",
        "tasks": [{"id": "task-a", "name": "Collect evidence", "instructions": "Collect evidence.", "order": 1}],
    }


def _runtime_projection(state="queued", version=1):
    return {
        "version": version,
        "state": state,
        "phase": "Task checkpoint",
        "progress": {"completed": 0, "total": 1},
        "memory": {"decisions": [], "units": []},
        "can_resume": False,
    }


class RealWorkflowRoutes:
    """The real route bodies over in-memory workflow storage and durable runtime doubles."""

    def __init__(self, *, group_id, workflow_id, role="Owner", feature_enabled=True, active=False):
        self.group_id = group_id
        self.workflow_id = workflow_id
        self.role = role
        self.user_id = ROLE_USERS[role]
        self.feature_enabled = feature_enabled
        self.created = 0
        self.logs = []
        self.workflows = {
            workflow_id: _workflow(
                workflow_id,
                group_id,
                active_run_id="active-run" if active else "",
                status="queued" if active else "idle",
            )
        }
        self.runs = {
            "active-run": {
                "id": "active-run",
                "workflow_id": workflow_id,
                "status": "queued",
                "success": False,
                "durable_execution": True,
                "started_at": "2026-09-25T19:00:00+00:00",
                "completed_at": None,
                "runtime": _runtime_projection("queued"),
            }
        } if active else {}

        assignment_ids = _load_pure_module("functions_group_assignment_ids", ASSIGNMENT_IDS_FILE)
        settings_namespace = {
            "normalize_group_workflow_allowed_group_ids": assignment_ids.normalize_group_workflow_allowed_group_ids,
        }
        _compile_into(
            SETTINGS_FILE,
            ("is_group_workflows_enabled_for_group", "get_group_workflow_management_roles"),
            settings_namespace,
        )
        self.settings = {
            "allow_group_workflows": True,
            "enable_group_workspaces": True,
            "require_group_assignment_for_group_workflows": not feature_enabled,
            "group_workflow_allowed_group_ids": [],
        }
        group_record = {
            "id": group_id,
            "name": "Group",
            "owner": {"id": ROLE_USERS["Owner"]},
            "admins": [ROLE_USERS["Admin"]],
            "documentManagers": [ROLE_USERS["DocumentManager"]],
            "users": [{"userId": user_id} for user_id in ROLE_USERS.values()],
        }
        functions_settings = SimpleNamespace(
            get_user_settings=lambda user_id: {"id": user_id, "settings": {"activeGroupOid": group_id}},
        )
        group_namespace = {
            "Iterable": Iterable,
            "find_group_by_id": lambda requested_id: copy.deepcopy(group_record) if requested_id == group_id else None,
            "functions_settings": functions_settings,
        }
        _compile_into(GROUP_FILE, ("get_user_role_in_group", "assert_group_role", "require_active_group"), group_namespace)

        def get_group_workflows(requested_group_id):
            return [copy.deepcopy(item) for item in self.workflows.values()] if requested_group_id == group_id else []

        def get_group_workflow(requested_group_id, requested_workflow_id):
            if requested_group_id != group_id:
                return None
            workflow = self.workflows.get(requested_workflow_id)
            return copy.deepcopy(workflow) if workflow else None

        def save_group_workflow(requested_group_id, payload, actor_user_id, user_info=None):
            if requested_group_id != group_id:
                raise LookupError("Workflow not found.")
            workflow_id = str(payload.get("id") or f"created-{self.created + 1}").strip()
            existing = self.workflows.get(workflow_id)
            if payload.get("id") and existing is None:
                raise LookupError("Workflow not found.")
            self.created += 1
            saved = {
                **(existing or {}),
                **copy.deepcopy(payload),
                "id": workflow_id,
                "group_id": group_id,
                "user_id": (existing or {}).get("user_id") or actor_user_id,
                "status": (existing or {}).get("status") or "idle",
                "active_run_id": (existing or {}).get("active_run_id", ""),
                "reference_inputs": copy.deepcopy(payload.get("reference_inputs", [])),
                "durable_execution": bool(payload.get("durable_execution", (existing or {}).get("durable_execution", False))),
                "alert_mode": payload.get("alert_mode", "off"),
                "alert_priority": payload.get("alert_priority", "none"),
                "alert_rules": copy.deepcopy(payload.get("alert_rules", [])),
                "alert_evaluation": copy.deepcopy(payload.get("alert_evaluation", {"on_error": "skip"})),
                "file_sync": copy.deepcopy(payload.get("file_sync", {
                    "enabled": False,
                    "wait_mode": "complete",
                    "continue_mode": "always",
                    "use_changed_documents": True,
                    "sources": [],
                })),
                "definition_revision": f"revision:{workflow_id}:{self.created + 1}",
            }
            self.workflows[workflow_id] = saved
            return copy.deepcopy(saved)

        def delete_group_workflow(requested_group_id, requested_workflow_id):
            if requested_group_id != group_id or requested_workflow_id not in self.workflows:
                return False
            del self.workflows[requested_workflow_id]
            return True

        def update_group_workflow_runtime_fields(requested_group_id, requested_workflow_id, updates):
            workflow = self.workflows[requested_workflow_id]
            workflow.update(copy.deepcopy(updates))
            return copy.deepcopy(workflow)

        def get_group_workflow_run(requested_group_id, run_id):
            if requested_group_id != group_id:
                return None
            run = self.runs.get(run_id)
            return copy.deepcopy(run) if run else None

        def save_group_workflow_run(requested_group_id, run_record):
            self.runs[run_record["id"]] = copy.deepcopy(run_record)
            return copy.deepcopy(run_record)

        def queue_durable_workflow_run(workflow, *, actor_user_id, trigger_source="manual", request_id=None, invocation_metadata=None):
            run_id = f"{workflow['id']}-run-1"
            runtime = _runtime_projection("queued")
            run = {
                "id": run_id,
                "workflow_id": workflow["id"],
                "status": "queued",
                "success": False,
                "durable_execution": True,
                "started_at": "2026-09-25T19:00:00+00:00",
                "completed_at": None,
                "runtime": runtime,
            }
            self.runs[run_id] = copy.deepcopy(run)
            bound = self.workflows[workflow["id"]]
            bound.update({"active_run_id": run_id, "status": "queued"})
            return {"success": True, "run": copy.deepcopy(run), "workflow": copy.deepcopy(bound), "runtime": runtime}

        def cancel_durable_workflow_run(workflow, run_id, *, actor_user_id):
            runtime = _runtime_projection("cancelled", version=2)
            run = self.runs.get(run_id) or {"id": run_id, "workflow_id": workflow["id"], "durable_execution": True}
            run.update({"status": "cancelled", "durable_execution": True, "runtime": runtime})
            self.runs[run_id] = copy.deepcopy(run)
            current = self.workflows[workflow["id"]]
            current.update({"active_run_id": "", "status": "cancelled"})
            return {"run": copy.deepcopy(run), "workflow": copy.deepcopy(current)}

        namespace = {
            "request": request,
            "jsonify": jsonify,
            "session": session,
            "logging": logging,
            "datetime": __import__("datetime").datetime,
            "timezone": __import__("datetime").timezone,
            "AzureError": RuntimeError,
            "RuntimeUnavailable": RuntimeError,
            "WorkflowRuntimeConflict": type("WorkflowRuntimeConflict", (RuntimeError,), {
                "code": "workflow_conflict",
                "public_message": "Workflow conflict.",
            }),
            "WorkflowDefinitionConflict": RuntimeError,
            "WorkflowDefinitionError": RuntimeError,
            "WorkflowPublicValidationError": RuntimeError,
            "AnalysisResultUnavailable": RuntimeError,
            "M365_ACTIVE_STATES": ("waiting_approval", "waiting_sign_in"),
            "GROUP_WORKFLOW_MEMBER_ROLES": GROUP_WORKFLOW_MEMBER_ROLES,
            "get_current_user_id": lambda: self.user_id,
            "get_current_user_info": lambda: {"id": self.user_id, "roles": ["User"]},
            "_get_current_user_info_with_roles": lambda: {"id": self.user_id, "roles": ["User"]},
            "get_settings": lambda: copy.deepcopy(self.settings),
            "is_group_workflows_enabled_for_group": settings_namespace["is_group_workflows_enabled_for_group"],
            "get_group_workflow_management_roles": settings_namespace["get_group_workflow_management_roles"],
            "assert_group_role": group_namespace["assert_group_role"],
            "require_active_group": group_namespace["require_active_group"],
            "authorize_workflow_run_read": lambda *args, **kwargs: True,
            "_prepare_workflow_url_access_payload": lambda payload, user_id: payload,
            "get_group_workflows": get_group_workflows,
            "get_group_workflow": get_group_workflow,
            "save_group_workflow": save_group_workflow,
            "delete_group_workflow": delete_group_workflow,
            "update_group_workflow_runtime_fields": update_group_workflow_runtime_fields,
            "get_group_workflow_run": get_group_workflow_run,
            "save_group_workflow_run": save_group_workflow_run,
            "queue_durable_workflow_run": queue_durable_workflow_run,
            "cancel_durable_workflow_run": cancel_durable_workflow_run,
            "log_event": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "log_workflow_creation": lambda **kwargs: None,
            "log_workflow_update": lambda **kwargs: None,
            "log_workflow_deletion": lambda **kwargs: None,
            "acquire_distributed_task_lock": lambda *args, **kwargs: {"id": "lock"},
            "release_distributed_task_lock": lambda *args, **kwargs: None,
            "create_workflow_run_id": lambda: "sync-run-1",
            "run_group_workflow": lambda *args, **kwargs: {
                "success": True,
                "run": {"id": kwargs.get("run_id"), "workflow_id": workflow_id, "status": "completed"},
                "workflow_updates": {"status": "idle", "active_run_id": ""},
            },
            "workflow_result_runtime_status": lambda result: (result.get("run") or {}).get("status", "idle"),
            "workflow_result_is_waiting": lambda result: False,
            "compute_next_run_at": lambda *args, **kwargs: None,
        }
        _compile_into(ROUTES_FILE, (*ROUTE_CLASSES, *ROUTE_HELPERS, *ROUTE_FUNCTIONS), namespace)
        app = Flask("group-workflow-fixture-parity")
        app.config.update(TESTING=True, SECRET_KEY="fixture-only-session-signing")
        blueprint = Blueprint("backend_workflows", __name__)
        blueprint.add_url_rule("/api/group/workflows", view_func=namespace["get_group_workflows_route"], methods=["GET"])
        blueprint.add_url_rule("/api/group/workflows", view_func=namespace["save_group_workflow_route"], methods=["POST"])
        blueprint.add_url_rule(
            "/api/group/workflows/<workflow_id>",
            view_func=namespace["delete_group_workflow_route"],
            methods=["DELETE"],
        )
        blueprint.add_url_rule(
            "/api/group/workflows/<workflow_id>/run",
            view_func=namespace["run_group_workflow_route"],
            methods=["POST"],
        )
        blueprint.add_url_rule(
            "/api/group/workflows/<workflow_id>/cancel",
            view_func=namespace["cancel_active_group_workflow_run"],
            methods=["POST"],
        )
        app.register_blueprint(blueprint)
        self.client = app.test_client()
        with self.client.session_transaction() as state:
            state["user"] = {"oid": self.user_id, "roles": ["User"]}

    def request(self, method, path, *, query=None, body=None):
        response = self.client.open(path, method=method, query_string=query or {}, json=body)
        return response.status_code, response.get_json()


class ModelledGroupWorkspace:
    def __init__(self, *, role="Owner", feature_enabled=True, active=False):
        self.fixture = GroupWorkspaceFixture(_FakePage())
        self.group_id = SHELL_GROUP_ID
        self.workflow_id = SHELL_WORKFLOW_ID
        self.fixture.groups[self.group_id]["role"] = role
        self.fixture.workflow_groups_enabled = {self.group_id} if feature_enabled else set()
        workflow = self.fixture.workflows[self.group_id][0]
        workflow.update(_workflow(self.workflow_id, self.group_id))
        if active:
            workflow.update({"active_run_id": "active-run", "status": "queued"})

    def request(self, method, path, *, query=None, body=None):
        route = _FakeRoute(path)
        entry = ApiRequest(method, path, {key: [value] for key, value in (query or {}).items()}, copy.deepcopy(body))
        self.fixture._dispatch(route, entry)
        return route.status, _round_trip(route.payload)


class ModelledWorkflowEditor:
    def __init__(self, *, role="Owner", feature_enabled=True, active=False):
        self.fixture = WorkflowEditorFixture(_FakePage(f"{ORIGIN}/v2/groups/{EDITOR_GROUP_ID}/workflows"))
        self.group_id = EDITOR_GROUP_ID
        self.workflow_id = EDITOR_WORKFLOW_ID
        self.fixture.group_role = role
        self.fixture.group_can_manage = role in {"Owner", "Admin"}
        self.fixture.group_workflow_enabled = {self.group_id} if feature_enabled else set()
        self.fixture.group_workflows[self.group_id][self.workflow_id] = _workflow(
            self.workflow_id,
            self.group_id,
            name="Group review workflow",
        )
        if active:
            workflow = self.fixture.group_workflows[self.group_id][self.workflow_id]
            workflow.update({"active_run_id": "active-run", "status": "queued"})
            self.fixture.workflow_runs[self.workflow_id] = [{
                "id": "active-run",
                "workflow_id": self.workflow_id,
                "status": "queued",
                "success": False,
                "durable_execution": True,
                "started_at": "2026-09-25T19:00:00+00:00",
                "completed_at": None,
            }]
            self.fixture.workflow_runtimes[("group", self.workflow_id, "active-run")] = _runtime_projection("queued")

    def request(self, method, path, *, query=None, body=None):
        route = _FakeRoute(path)
        entry = ApiRequest(method, path, {key: [value] for key, value in (query or {}).items()}, copy.deepcopy(body))
        self.fixture._dispatch(route, entry)
        return route.status, _round_trip(route.payload)


FIXTURE_MODELS = (
    pytest.param("group-workspace", ModelledGroupWorkspace, SHELL_GROUP_ID, SHELL_WORKFLOW_ID, id="group-workspace"),
    pytest.param("workflow-editor", ModelledWorkflowEditor, EDITOR_GROUP_ID, EDITOR_WORKFLOW_ID, id="workflow-editor"),
)


def _comparable(answer):
    status, payload = answer

    def strip(value):
        if isinstance(value, dict):
            if set(value) >= {"version", "state"} and "memory" in value:
                return {
                    "version": value.get("version"),
                    "state": value.get("state"),
                    "can_resume": value.get("can_resume", False),
                }
            return {
                key: "<generated-id>" if key in {"id", "active_run_id"} and item else strip(item)
                for key, item in value.items()
                if key not in {"started_at", "completed_at", "definition_revision", "user_id"}
            }
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return status, strip(payload)


def _assert_same(real_answer, fixture_answer, label):
    assert _comparable(fixture_answer) == _comparable(real_answer), (
        f"{label}\n  server:  {real_answer}\n  fixture: {fixture_answer}"
    )


def _query(group_id):
    return {"group_id": group_id}


@pytest.mark.parametrize("fixture_name,model,group_id,workflow_id", FIXTURE_MODELS)
@pytest.mark.parametrize("role", list(ROLE_USERS))
@pytest.mark.parametrize("operation", ["list", "save", "run", "cancel", "delete"])
def test_every_role_meets_the_real_route_answer(fixture_name, model, group_id, workflow_id, role, operation):
    active = operation == "cancel"
    real = RealWorkflowRoutes(group_id=group_id, workflow_id=workflow_id, role=role, active=active)
    fixture = model(role=role, active=active)
    if operation == "list":
        real_answer = real.request("GET", "/api/group/workflows", query=_query(group_id))
        fixture_answer = fixture.request("GET", "/api/group/workflows", query=_query(group_id))
    elif operation == "save":
        body = _save_payload(workflow_id, group_id)
        real_answer = real.request("POST", "/api/group/workflows", query=_query(group_id), body=body)
        fixture_answer = fixture.request("POST", "/api/group/workflows", query=_query(group_id), body=body)
    elif operation == "run":
        path = f"/api/group/workflows/{workflow_id}/run"
        real_answer = real.request("POST", path, query=_query(group_id), body={})
        fixture_answer = fixture.request("POST", path, query=_query(group_id), body={})
    elif operation == "cancel":
        path = f"/api/group/workflows/{workflow_id}/cancel"
        real_answer = real.request("POST", path, query=_query(group_id), body={})
        fixture_answer = fixture.request("POST", path, query=_query(group_id), body={})
    else:
        path = f"/api/group/workflows/{workflow_id}"
        real_answer = real.request("DELETE", path, query=_query(group_id))
        fixture_answer = fixture.request("DELETE", path, query=_query(group_id))
    _assert_same(real_answer, fixture_answer, f"{fixture_name} {role} {operation}")


@pytest.mark.parametrize("fixture_name,model,group_id,workflow_id", FIXTURE_MODELS)
@pytest.mark.parametrize("suffix,method,body", [
    ("/missing/run", "POST", {}),
    ("/missing/cancel", "POST", {}),
    ("/missing", "DELETE", None),
])
def test_missing_workflow_is_the_real_404(fixture_name, model, group_id, workflow_id, suffix, method, body):
    real = RealWorkflowRoutes(group_id=group_id, workflow_id=workflow_id)
    fixture = model()
    path = f"/api/group/workflows{suffix}"
    real_answer = real.request(method, path, query=_query(group_id), body=body)
    fixture_answer = fixture.request(method, path, query=_query(group_id), body=body)
    _assert_same(real_answer, fixture_answer, f"{fixture_name} missing {method} {path}")


@pytest.mark.parametrize("fixture_name,model,group_id,workflow_id", FIXTURE_MODELS)
def test_cancel_without_active_run_is_the_real_conflict(fixture_name, model, group_id, workflow_id):
    real = RealWorkflowRoutes(group_id=group_id, workflow_id=workflow_id)
    fixture = model()
    path = f"/api/group/workflows/{workflow_id}/cancel"
    real_answer = real.request("POST", path, query=_query(group_id), body={})
    fixture_answer = fixture.request("POST", path, query=_query(group_id), body={})
    _assert_same(real_answer, fixture_answer, f"{fixture_name} inactive cancel")


@pytest.mark.parametrize("fixture_name,model,group_id,workflow_id", FIXTURE_MODELS)
@pytest.mark.parametrize("operation", ["list", "save", "run", "cancel", "delete"])
def test_group_workflows_switched_off_is_refused_like_the_route(fixture_name, model, group_id, workflow_id, operation):
    real = RealWorkflowRoutes(group_id=group_id, workflow_id=workflow_id, feature_enabled=False, active=True)
    fixture = model(feature_enabled=False, active=True)
    if operation == "list":
        real_answer = real.request("GET", "/api/group/workflows", query=_query(group_id))
        fixture_answer = fixture.request("GET", "/api/group/workflows", query=_query(group_id))
    elif operation == "save":
        body = _save_payload(workflow_id, group_id)
        real_answer = real.request("POST", "/api/group/workflows", query=_query(group_id), body=body)
        fixture_answer = fixture.request("POST", "/api/group/workflows", query=_query(group_id), body=body)
    elif operation == "run":
        path = f"/api/group/workflows/{workflow_id}/run"
        real_answer = real.request("POST", path, query=_query(group_id), body={})
        fixture_answer = fixture.request("POST", path, query=_query(group_id), body={})
    elif operation == "cancel":
        path = f"/api/group/workflows/{workflow_id}/cancel"
        real_answer = real.request("POST", path, query=_query(group_id), body={})
        fixture_answer = fixture.request("POST", path, query=_query(group_id), body={})
    else:
        path = f"/api/group/workflows/{workflow_id}"
        real_answer = real.request("DELETE", path, query=_query(group_id))
        fixture_answer = fixture.request("DELETE", path, query=_query(group_id))
    _assert_same(real_answer, fixture_answer, f"{fixture_name} feature-off {operation}")


@pytest.mark.parametrize("fixture_name,model,group_id,workflow_id", FIXTURE_MODELS)
def test_grid_is_not_vacuous(fixture_name, model, group_id, workflow_id):
    real_user = RealWorkflowRoutes(group_id=group_id, workflow_id=workflow_id, role="User")
    run_answer = real_user.request(
        "POST",
        f"/api/group/workflows/{workflow_id}/run",
        query=_query(group_id),
        body={},
    )
    delete_answer = real_user.request(
        "DELETE",
        f"/api/group/workflows/{workflow_id}",
        query=_query(group_id),
    )
    assert run_answer[0] == 202, f"{fixture_name}: real route must accept a User run, got {run_answer}"
    assert delete_answer == (403, {"error": "Insufficient permissions for this group"}), (
        f"{fixture_name}: real route must refuse a User delete, got {delete_answer}"
    )
