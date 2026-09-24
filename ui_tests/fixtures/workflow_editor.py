# workflow_editor.py
"""
Closed API fixtures for the native V2 workflow editor.
Version: 0.261.141
Implemented in: 0.261.108
Group File Sync, alert handoff and personal-scope trap modelling added in: 0.261.141

Group File Sync requests are answered by the real server functions, compiled from source:
`_serialize_workflow_file_sync_source` builds the source list, and `_normalize_file_sync_config`,
`_normalize_schedule` and the Monitor File Sync trigger rules of `save_group_workflow` validate a
group save, with the save route's status mapping. Only the source store, group File Sync
enablement and the viewer's group role are fixture state.

Every request made while the page is a group page (`/v2/groups...`) is checked with the general
`personal_scope_leak` trap, in `_route`, so every workflow fixture subclass enforces it.
"""

import ast
import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect
from ui_tests.fixtures.group_workspace import group_context

from ui_tests.fixtures.workspace_authoring import (
    AGENT_ID,
    GLOBAL_AGENT_ID,
    ORIGIN,
    OWNER_ID,
    STATIC_ROOT,
    ApiRequest,
    WorkspaceAuthoringFixture,
    connect_options,  # noqa: F401
    personal_scope_leak,
)

APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Validate the browser's actual data-flow payload with production helpers.
from functions_workflow_definitions import (
    WorkflowDefinitionError,
    normalize_workflow_definition,
    workflow_definition_revision,
)


WORKFLOW_ID = "workflow-v2-review"
DURABLE_WORKFLOW_ID = "durable-approval-workflow"
UNSUPPORTED_WORKFLOW_ID = "workflow-v3-future"
GROUP_ID = "group-alpha"
SECOND_GROUP_ID = "group-beta"
SPA_INDEX = STATIC_ROOT / "v2" / "index.html"
FILE_SYNC_SOURCES_PATH = "/api/group/workflows/file-sync-sources"
FILE_SYNC_FIXTURE_SECRET = "fixture-file-sync-password"
# The group save route's status mapping (`save_group_workflow_route`).
GROUP_SAVE_ERRORS = {
    ValueError: (400, "Invalid workflow settings. Review the task, runner, trigger, and document inputs."),
    LookupError: (404, "The workflow or one of its sources is not available."),
    PermissionError: (403, "The selected group or workflow sources are not allowed."),
}


def _production_code(module_name, names):
    """Compile named functions and literal constants from a production module, without importing it."""
    source_file = APP_ROOT / module_name
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
        or isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
    ]
    found = {
        node.name if isinstance(node, ast.FunctionDef)
        else next(target.id for target in node.targets if isinstance(target, ast.Name) and target.id in names)
        for node in nodes
    }
    assert found == set(names), f"{module_name} no longer defines {sorted(set(names) - found)}"
    return compile(ast.Module(body=nodes, type_ignores=[]), str(source_file), "exec")


# The real server rules for group File Sync, compiled once and bound to each fixture's state.
FILE_SYNC_CODE = (
    _production_code("functions_file_sync.py", (
        "FILE_SYNC_SCOPE_PERSONAL", "FILE_SYNC_SCOPE_GROUP", "FILE_SYNC_SCOPE_PUBLIC", "FILE_SYNC_MANAGER_ROLES",
    )),
    _production_code("functions_personal_workflows.py", (
        "WORKFLOW_SCHEDULE_UNITS", "WORKFLOW_FILE_SYNC_WAIT_MODES", "WORKFLOW_FILE_SYNC_CONTINUE_MODES",
        "WORKFLOW_FILE_SYNC_MAX_SOURCES", "_normalize_text", "_normalize_bool", "_normalize_schedule",
    )),
    _production_code("functions_group_workflows.py", ("_normalize_file_sync_config",)),
    _production_code("route_backend_workflows.py", ("_serialize_workflow_file_sync_source",)),
)


def group_file_sync_source(group_id, source_id, name, **fields):
    """A stored group File Sync source, including a credential the list must never return."""
    return {
        "id": source_id, "scope_type": "group", "group_id": group_id, "name": name,
        "source_type": "smb", "enabled": True, "auth": {"password": FILE_SYNC_FIXTURE_SECRET},
        **fields,
    }


def workflow_record(identifier=WORKFLOW_ID, **overrides):
    record = {
        "id": identifier,
        "definition_version": 2,
        "definition_revision": f"revision:{identifier}:1",
        "name": "Quarterly review workflow",
        "description": "Runs the recurring review.",
        "runner_type": "model",
        "model_endpoint_id": "workspace-model-endpoint",
        "model_id": "workspace-model",
        "chat_capabilities_enabled": True,
        "trigger_type": "manual",
        "schedule": {"unit": "minutes", "value": 30},
        "is_enabled": True,
        "error_handling": {"strategy": "halt", "retry_count": 1},
        "tasks": [
            {
                "id": "task-a",
                "type": "instructions",
                "name": "Collect evidence",
                "instructions": "Collect source evidence.",
                "order": 1,
                "runner": {"type": "inherit"},
                "output_contract": {
                    "kind": "records",
                    "expected_count": 3,
                    "identity_field": "id",
                    "require_complete_coverage": True,
                    "allow_partial": False,
                },
            },
            {
                "id": "task-b",
                "type": "instructions",
                "name": "Summarize evidence",
                "instructions": "Summarize findings.",
                "order": 2,
                "runner": {"type": "inherit"},
                "inputs": None,
                "reference_ids": None,
            },
        ],
        "reference_inputs": [],
        "file_sync": {"source_id": "legacy-source", "delete_policy": "preserve"},
        "alert_settings": {"owner_on_failure": True},
        "publication_options": {"publish_to_public_workspace": False},
        "metadata": {"legacy": {"kept": True}},
    }
    record.update(copy.deepcopy(overrides))
    return record


def editor_options(scope_type="personal", scope_id=None):
    return {
        "definition_version": 2,
        "supported_definition_versions": [1, 2, 3],
        "supported_node_kinds": ["task", "if", "route"],
        "flow_limits": {
            "max_nodes": 256, "max_depth": 4,
            "max_predicate_nodes": 100, "max_predicate_depth": 8,
            "max_executions": 5000, "deadline_seconds": 86400,
        },
        "can_manage": True,
        "max_tasks": 6,
        "agents": [
            {
                "id": AGENT_ID,
                "name": "workspace-reviewer",
                "display_name": "Workspace reviewer",
                "is_global": False,
                "is_group": scope_type == "group",
                **({"group_id": scope_id} if scope_id else {}),
            },
            {
                "id": GLOBAL_AGENT_ID,
                "name": "provided-reviewer",
                "display_name": "Provided reviewer",
                "is_global": True,
                "is_group": False,
            },
        ],
        "models": [
            {
                "endpoint_id": "workspace-model-endpoint",
                "model_id": "workspace-model",
                "label": "Workspace GPT",
                "provider": "aoai",
            }
        ],
        "default_model": {"label": "Default GPT", "valid": False},
        "scope": {"type": scope_type, **({"id": scope_id} if scope_id else {})},
    }


class WorkflowEditorFixture(WorkspaceAuthoringFixture):
    """Synthetic server for the real V2 workflow editor bundle."""

    def __init__(self, page: Page):
        super().__init__(page)
        self.active_group_id = None
        self.personal_workflows = {
            WORKFLOW_ID: workflow_record(),
            "agent-workflow": workflow_record(
                "agent-workflow",
                name="Agent review workflow",
                runner_type="agent",
                selected_agent={
                    "id": AGENT_ID,
                    "name": "workspace-reviewer",
                    "display_name": "Workspace reviewer",
                    "is_global": False,
                    "is_group": False,
                },
                tasks=[
                    {
                        "id": "agent-task",
                        "type": "instructions",
                        "name": "Agent task",
                        "instructions": "Use a provided reviewer for this step.",
                        "order": 1,
                        "runner": {
                            "type": "agent",
                            "selected_agent": {
                                "id": GLOBAL_AGENT_ID,
                                "name": "provided-reviewer",
                                "display_name": "Provided reviewer",
                                "is_global": True,
                                "is_group": False,
                            },
                        },
                    }
                ],
            ),
            "legacy-prompt-workflow": workflow_record(
                "legacy-prompt-workflow",
                name="Legacy prompt workflow",
                tasks=[],
                task_prompt="Use the legacy single prompt.",
                document_action={"type": "analyze", "document_ids": ["personal-brief"]},
            ),
            "active-workflow": workflow_record(
                "active-workflow",
                name="Active running workflow",
                active_run_id="active-run",
                status="running",
            ),
            DURABLE_WORKFLOW_ID: workflow_record(
                DURABLE_WORKFLOW_ID,
                name="Durable approval workflow",
                durable_execution=True,
                tasks=[
                    {
                        "id": "approval-task",
                        "type": "instructions",
                        "name": "Approval task",
                        "instructions": "Wait for approval before running.",
                        "order": 1,
                        "runner": {"type": "inherit"},
                        "approval": {
                            "required": True,
                            "message": "Review the checkpoint before this task starts.",
                        },
                    }
                ],
            ),
            UNSUPPORTED_WORKFLOW_ID: workflow_record(
                UNSUPPORTED_WORKFLOW_ID,
                definition_version=4,
                name="Future workflow",
            ),
        }
        self.group_workflows = {
            GROUP_ID: {
                "group-workflow": workflow_record(
                    "group-workflow",
                    name="Group review workflow",
                    group_id=GROUP_ID,
                    reference_inputs=[],
                )
            },
            SECOND_GROUP_ID: {},
        }
        self.workflow_writes = []
        self.m365_run_as_users = {
            "personal": [{"id": OWNER_ID, "display_name": "Workspace editor"}],
            GROUP_ID: [
                {"id": OWNER_ID, "display_name": "Workspace editor"},
                {"id": "group-reviewer", "display_name": "Group reviewer"},
            ],
            SECOND_GROUP_ID: [
                {"id": OWNER_ID, "display_name": "Workspace editor"},
                {"id": "group-beta-reviewer", "display_name": "Beta group reviewer"},
            ],
        }
        self.workflow_runs = {
            DURABLE_WORKFLOW_ID: [{
                "id": "durable-run-1",
                "workflow_id": DURABLE_WORKFLOW_ID,
                "status": "waiting_approval",
                "durable_execution": True,
                "started_at": "2026-09-16T12:00:00Z",
            }]
        }
        self.workflow_runtimes = {
            ("user", DURABLE_WORKFLOW_ID, "durable-run-1"): self.runtime_projection(
                state="waiting_approval",
                version=2,
                gate={
                    "id": "approval-gate-1",
                    "kind": "approval",
                    "unit_id": "approval-task",
                    "input_digest": "sha256:approval",
                    "reason": "Approval is required before Approval task starts.",
                    "choices": ["approve", "reject"],
                },
            )
        }
        self.runtime_can_decide = {("user", DURABLE_WORKFLOW_ID, "durable-run-1"): True}
        self.runtime_get_count = {}
        self.runtime_get_transitions = {}
        self.stale_next_decision = False
        self.stale_next_resume = False
        self.fail_next_decision_status = None
        self.fail_next_resume_status = None
        self.documents = [
            {
                "id": "personal-brief",
                "document_id": "personal-brief",
                "title": "Private brief",
                "file_name": "private-brief.pdf",
                "user_id": OWNER_ID,
            },
            {
                "id": "personal-second",
                "document_id": "personal-second",
                "title": "Second brief",
                "file_name": "second-brief.pdf",
                "user_id": OWNER_ID,
            },
        ]
        self.group_documents = {
            GROUP_ID: [
                {
                    "id": "group-brief",
                    "document_id": "group-brief",
                    "title": "Group brief",
                    "file_name": "group-brief.pdf",
                    "group_id": GROUP_ID,
                }
            ]
        }
        self.public_documents = [
            {
                "id": "public-policy",
                "document_id": "public-policy",
                "title": "Published policy",
                "file_name": "published-policy.pdf",
                "public_workspace_id": "public-handbook",
            }
        ]
        self.fail_next_run = False
        # Group File Sync state behind the real source-list and save rules compiled above.
        self.group_file_sync_enabled = {GROUP_ID: True, SECOND_GROUP_ID: True}
        self.group_file_sync_sources = {
            GROUP_ID: [
                group_file_sync_source(GROUP_ID, "finance-share", "Finance share"),
                group_file_sync_source(GROUP_ID, "archive-share", "Archive share", source_type="azure_blob", enabled=False),
            ],
            SECOND_GROUP_ID: [group_file_sync_source(SECOND_GROUP_ID, "beta-share", "Beta share")],
        }
        self.file_sync_source_reads = []
        self.classic_visits = []
        self.file_sync_rules = self._bind_file_sync_rules()

    def _group_role(self):
        return "Admin" if getattr(self, "group_can_manage", True) else "User"

    def _bind_file_sync_rules(self):
        """Run the compiled server functions against this fixture's source store and group role."""

        def get_authorized_sync_source(scope_type, source_id, user_id, scope_id=None, allowed_roles=None):
            self.file_sync_source_reads.append((scope_type, scope_id, source_id))
            if self._group_role() not in (allowed_roles or rules["FILE_SYNC_MANAGER_ROLES"]):
                raise PermissionError("Insufficient permissions for this group")
            for source in self.group_file_sync_sources.get(scope_id, []):
                if source.get("id") == source_id:
                    return copy.deepcopy(source)
            raise LookupError("File sync source not found")

        def sanitize_file_sync_source(source):
            sanitized = dict(source or {})
            sanitized.pop("auth", None)
            return sanitized

        rules = {
            "get_settings": dict,
            "get_authorized_sync_source": get_authorized_sync_source,
            "sanitize_file_sync_source": sanitize_file_sync_source,
            "is_file_sync_enabled_for_group": lambda settings, group_id, user_info=None: bool(
                self.group_file_sync_enabled.get(group_id)
            ),
        }
        for code in FILE_SYNC_CODE:
            exec(code, rules)
        return rules

    def _group_file_sync_sources(self, route, entry):
        """GET /api/group/workflows/file-sync-sources, resolved like the real route with ?group_id."""
        group_id = entry.query.get("group_id", [""])[0].strip()
        if not group_id:
            # Without group_id the real route falls back to the account's active group, which a
            # group page must never rely on.
            self.unexpected_requests.append(f"GET {entry.path} without an explicit group_id")
            self._json(route, {"error": "No active group selected"}, 400)
            return
        if group_id not in self.group_file_sync_sources:
            self._json(route, {"error": "Group not found"}, 404)
            return
        if self._group_role() not in self.file_sync_rules["FILE_SYNC_MANAGER_ROLES"]:
            # The route refuses members, and a member's read-only editor has no reason to ask.
            self.unexpected_requests.append(f"GET {entry.path} (a group member cannot list File Sync sources)")
            self._json(route, {"error": "Insufficient permissions for this group"}, 403)
            return
        if not self.group_file_sync_enabled.get(group_id):
            self._json(route, {"sources": []})
            return
        serialize = self.file_sync_rules["_serialize_workflow_file_sync_source"]
        self._json(route, {"sources": [
            serialize("group", group_id, source)
            for source in self.group_file_sync_sources[group_id]
            if source.get("id")
        ]})

    def _group_save_refusal(self, body, existing, group_id):
        """Apply the server's File Sync, trigger and schedule rules to a group save; return the stored file_sync."""
        file_sync = self.file_sync_rules["_normalize_file_sync_config"](
            OWNER_ID, group_id, body, existing_workflow=existing, user_info={"roles": ["User"]},
        )
        # The Monitor File Sync trigger and schedule rules inline in `save_group_workflow`.
        trigger_type = str(body.get("trigger_type") or "").strip().lower()
        if trigger_type == "file_sync":
            if not file_sync.get("enabled"):
                raise ValueError("Monitor File Sync Changes workflows require File Sync before run.")
            if file_sync.get("wait_mode") != "complete":
                raise ValueError("Monitor File Sync Changes workflows must wait for sync completion.")
            if file_sync.get("continue_mode") != "changed":
                raise ValueError("Monitor File Sync Changes workflows must continue only when changes are found.")
        if trigger_type in {"interval", "file_sync"}:
            self.file_sync_rules["_normalize_schedule"](body.get("schedule"))
        return file_sync

    def runtime_projection(self, state="running", version=1, gate=None, can_resume=False):
        runtime = {
            "version": version,
            "state": state,
            "phase": "Task checkpoint",
            "progress": {"completed": 1 if state.startswith("waiting") else 0, "total": 2},
            "memory": {
                "decisions": [],
                "units": [
                    {
                        "unit_id": "collect-evidence",
                        "state": "completed",
                        "attempt": 1,
                        "replay_safe": True,
                        "output_available": True,
                    },
                    {
                        "unit_id": "approval-task",
                        "state": state,
                        "attempt": 1,
                        "replay_safe": False,
                        "output_available": False,
                    },
                ],
            },
        }
        if gate:
            runtime["gate"] = gate
        if can_resume:
            runtime["can_resume"] = True
        return runtime

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["workspace"]["sections"]["workflows"] = {
            "enabled": True,
            "reason": None,
            "group": "automation",
        }
        payload["features"]["enable_group_workspaces"] = True
        payload["scope"]["active_group_id"] = self.active_group_id
        payload["scope"]["groups"] = [
            {"id": GROUP_ID, "name": "Alpha Group"},
            {"id": SECOND_GROUP_ID, "name": "Beta Group"},
        ]
        payload["scope"]["public_workspaces"] = [
            {"id": "public-handbook", "name": "Published handbook"},
        ]
        return payload

    def select_group(self, group_id):
        """Use the actual selector and shared rail to reach the group's workflows."""
        selector = self.page.get_by_label("Group workspace", exact=True)
        selector.select_option(group_id)
        expect(self.page).to_have_url(re.compile(rf"/v2/groups/{re.escape(group_id)}(?:/[^?]+)?(?:\?.*)?$"))
        expect(selector).to_be_enabled()
        self.page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role(
            "link", name="Workflows", exact=True,
        ).click()

    @property
    def non_navigation_writes(self):
        return [
            entry for entry in self.writes
            if (entry.method, entry.path) != ("PATCH", "/api/groups/setActive")
        ]

    def _route(self, route: Route):
        request = route.request
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected_requests.append(f"{request.method} {request.url}")
            route.abort()
            return
        path = unquote(parsed.path)
        if request.method == "GET" and re.fullmatch(
            r"/v2/(workspace(?:/(?:agents|actions|prompts|documents|workflows)(?:/[^/]+)?)?|groups(?:/[^/]+(?:/[^/]+)?)?|chat)",
            path,
        ):
            route.fulfill(path=str(SPA_INDEX), content_type="text/html")
            return
        if request.method == "GET" and path == "/group_workspaces":
            # The classic handoff target. The active group at arrival is what classic would show.
            self.classic_visits.append((path, self.active_group_id))
            route.fulfill(content_type="text/html", body="<html><body>Classic handoff target</body></html>")
            return
        if request.method == "GET" and path.startswith("/static/"):
            asset = (STATIC_ROOT / path.removeprefix("/static/")).resolve()
            if asset.is_relative_to(STATIC_ROOT.resolve()) and asset.is_file():
                self.loaded_assets.add(path)
                route.fulfill(path=str(asset))
                return
            self.unexpected_requests.append(f"Missing local asset: {path}")
            route.fulfill(status=404, body="Fixture asset not found.")
            return
        body = None
        if request.post_data:
            if "application/json" in request.headers.get("content-type", ""):
                body = request.post_data_json
            else:
                body = request.post_data
        entry = ApiRequest(request.method, path, parse_qs(parsed.query), copy.deepcopy(body))
        self.requests.append(entry)
        if request.method != "GET":
            self.writes.append(entry)
        leak = personal_scope_leak(path, entry.query)
        if leak and urlsplit(self.page.url).path.startswith("/v2/groups"):
            # A group workflow page resolves every resource through a group-scoped route, so a
            # personal read here is a leak. It is recorded, never answered, and never allowlisted.
            self.unexpected_requests.append(f"{request.method} {path} ({leak} from a group page)")
            self._json(route, {"error": "Personal-scope reads are not available on group pages."}, 500)
            return
        for index, (method, failed_path, status, payload) in enumerate(self.failures):
            if (method, failed_path) == (entry.method, path):
                self.failures.pop(index)
                self._json(route, payload, status)
                return
        if (entry.method, path) in self.deferred_paths:
            self.deferred_paths.remove((entry.method, path))
            self.pending_responses.append((route, entry))
            return
        self._dispatch(route, entry)

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path.startswith("/api/v2/workspaces/group/") and method == "GET":
            group_id = path.rsplit("/", 1)[-1]
            assert group_id in (GROUP_ID, SECOND_GROUP_ID), entry
            context = group_context(
                group_id, "Alpha Group" if group_id == GROUP_ID else "Beta Group",
                role="Admin" if getattr(self, "group_can_manage", True) else "User",
            )
            self._json(route, context)
        elif path == "/api/groups/setActive" and method == "PATCH":
            assert entry.body["groupId"] in (GROUP_ID, SECOND_GROUP_ID), entry
            self.active_group_id = entry.body["groupId"]
            self._json(route, {"message": "Active group selected."})
        elif path == "/api/groups" and method == "GET":
            self._json(route, {
                "groups": [
                    {"id": GROUP_ID, "name": "Alpha Group", "userRole": "Admin"},
                    {"id": SECOND_GROUP_ID, "name": "Beta Group", "userRole": "Admin"},
                ],
                "page": 1,
                "page_size": 25,
                "total_count": 2,
            })
        elif path == "/api/plugins/agent-targets" and method == "GET" and entry.query.get("scope") == ["group"]:
            assert entry.query.get("group_id") == [GROUP_ID], entry
            self._json(route, {
                "targets": [],
                "can_manage": True,
                "scope_type": "group",
                "scope_id": GROUP_ID,
            })
        elif path in ("/api/group/plugins", "/api/group/agents") and method == "GET":
            assert entry.query.get("group_id") == [GROUP_ID], entry
            self._json(route, {"actions": [], "agents": []} if path.endswith("/plugins") else {"agents": []})
        elif path in ("/api/user/workflows/editor-options", "/api/group/workflows/editor-options") and method == "GET":
            if path.startswith("/api/group/"):
                assert entry.query.get("group_id") == [GROUP_ID], entry
                options = editor_options("group", GROUP_ID)
                # The real options grant management from the viewer's group role.
                options["can_manage"] = getattr(self, "group_can_manage", True)
                self._json(route, options)
            else:
                assert not entry.query, entry
                self._json(route, editor_options())
        elif path == FILE_SYNC_SOURCES_PATH and method == "GET":
            self._group_file_sync_sources(route, entry)
        elif path == "/api/workflows/m365-run-as-users" and method == "GET":
            if entry.query.get("scope") == ["group"]:
                group_id = entry.query.get("group_id", [None])[0]
                assert group_id in self.group_workflows, entry
                assert entry.query == {"scope": ["group"], "group_id": [group_id]}, entry
                users = self.m365_run_as_users[group_id]
            else:
                assert entry.query == {"scope": ["personal"]}, entry
                users = self.m365_run_as_users["personal"]
            self._json(route, {"users": users})
        elif path == "/api/user/workflows" and method in ("GET", "POST"):
            self._workflow_collection(route, entry, self.personal_workflows, "personal")
        elif path == "/api/group/workflows" and method in ("GET", "POST"):
            group_id = entry.query.get("group_id", [""])[0]
            assert group_id == GROUP_ID, entry
            self._workflow_collection(route, entry, self.group_workflows.setdefault(group_id, {}), "group", group_id)
        elif re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/runtime(?:/(?:decision|resume))?", path):
            self._workflow_runtime(route, entry)
        elif re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/tasks/[^/]+/result", path):
            self._workflow_resource(route, entry)
        elif re.fullmatch(r"/api/(user|group)/workflows/[^/]+(?:/(?:run|cancel|runs)(?:/[^/]+(?:/items)?)?)?", path):
            self._workflow_resource(route, entry)
        elif path == "/api/documents" and method == "GET":
            self._json(route, {"documents": self.documents, "total_count": len(self.documents)})
        elif path == "/api/group_documents" and method == "GET":
            assert entry.query.get("group_ids") == [GROUP_ID], entry
            docs = self.group_documents.get(GROUP_ID, [])
            self._json(route, {"documents": docs, "total_count": len(docs)})
        elif path == "/api/public_workspace_documents" and method == "GET":
            self._json(route, {"documents": self.public_documents, "total_count": len(self.public_documents)})
        else:
            super()._dispatch(route, entry)

    def _workflow_collection(self, route, entry, workflows, scope_type, group_id=None):
        if entry.method == "GET":
            self._json(route, {"workflows": list(workflows.values())})
            return
        assert isinstance(entry.body, dict), entry
        assert entry.body.get("definition_version") in {2, 3}, entry
        if entry.body.get("runner_type") == "agent":
            assert isinstance(entry.body.get("selected_agent"), dict), entry.body
        for task in entry.body.get("tasks", []):
            if task.get("runner", {}).get("type") == "agent":
                assert isinstance(task.get("runner", {}).get("selected_agent"), dict), task
        if scope_type == "group":
            assert entry.body.get("group_id") == group_id, entry
        identifier = entry.body.get("id") or f"{scope_type}-created-{len(workflows) + 1}"
        existing = workflows.get(identifier)
        if existing and entry.body.get("definition_revision") != existing.get("definition_revision"):
            self._json(route, {"error": "stale workflow definition"}, 409)
            return
        file_sync = None
        if scope_type == "group":
            if self._group_role() not in ("Owner", "Admin"):
                self.unexpected_requests.append(f"POST {entry.path} (a group member cannot save workflows)")
                self._json(route, {"error": GROUP_SAVE_ERRORS[PermissionError][1]}, 403)
                return
            try:
                file_sync = self._group_save_refusal(entry.body, existing, group_id)
            except (ValueError, LookupError, PermissionError) as exc:
                status, message = next(
                    mapped for error_type, mapped in GROUP_SAVE_ERRORS.items() if isinstance(exc, error_type)
                )
                self._json(route, {"error": message}, status)
                return
        validation_payload = copy.deepcopy(entry.body)
        if existing:
            # Human-readable fixture revisions are checked above. The structural
            # contract uses the production authored-content revision algorithm.
            validation_payload["definition_revision"] = workflow_definition_revision(existing)
        try:
            definition = normalize_workflow_definition(
                validation_payload, existing, validation_payload["tasks"],
                user_id=OWNER_ID, group_id=group_id or "",
            )
        except WorkflowDefinitionError as exc:
            self._json(route, {"error": str(exc)}, 400)
            return
        saved = {**copy.deepcopy(entry.body), **definition}
        if file_sync is not None:
            # The server stores its own normalization, including each source's current name and type.
            saved["file_sync"] = file_sync
        saved["id"] = identifier
        saved["definition_revision"] = f"revision:{identifier}:{len(self.workflow_writes) + 2}"
        workflows[identifier] = saved
        self.workflow_writes.append(entry)
        self._json(route, {"success": True, "workflow": saved})

    def _workflow_resource(self, route, entry):
        path_parts = entry.path.split("/")
        scope_type = path_parts[2]
        workflow_id = path_parts[4]
        workflows = self.personal_workflows
        if scope_type == "group":
            group_id = entry.query.get("group_id", [""])[0]
            assert group_id == GROUP_ID, entry
            workflows = self.group_workflows[GROUP_ID]
        assert workflow_id in workflows, entry
        if entry.method == "DELETE":
            del workflows[workflow_id]
            self._json(route, {"success": True})
        elif entry.path.endswith("/run") and entry.method == "POST":
            if workflows[workflow_id].get("durable_execution") is True:
                run_id = f"{workflow_id}-run-{len(self.workflow_runs.get(workflow_id, [])) + 1}"
                run = {
                    "id": run_id,
                    "workflow_id": workflow_id,
                    "status": "queued",
                    "durable_execution": True,
                    "started_at": "2026-09-16T13:00:00Z",
                }
                runtime = self.runtime_projection(state="queued", version=1)
                key = (scope_type, workflow_id, run_id)
                self.workflow_runs[workflow_id] = [run, *self.workflow_runs.get(workflow_id, [])]
                self.workflow_runtimes[key] = runtime
                self.runtime_can_decide[key] = True
                workflows[workflow_id]["active_run_id"] = run_id
                workflows[workflow_id]["status"] = "queued"
                self._json(route, {
                    "success": True,
                    "run": run,
                    "workflow": workflows[workflow_id],
                    "runtime": runtime,
                }, 202)
                return
            if self.fail_next_run:
                self.fail_next_run = False
                workflows[workflow_id]["active_run_id"] = None
                workflows[workflow_id]["status"] = "failed"
                self.expected_http_errors.add((route.request.url, 400))
                route.fulfill(status=400, json={"error": "Workflow run completed with failed tasks."})
                return
            workflows[workflow_id]["active_run_id"] = "run-1"
            workflows[workflow_id]["status"] = "running"
            self._json(route, {"id": "run-1", "workflow_id": workflow_id, "status": "running"})
        elif entry.path.endswith("/cancel") and entry.method == "POST":
            workflows[workflow_id]["active_run_id"] = None
            workflows[workflow_id]["status"] = "cancelled"
            for key, runtime in list(self.workflow_runtimes.items()):
                if key[1] == workflow_id and runtime["state"] not in {
                    "cancelled", "failed", "invalid", "incomplete", "completed", "completed_partial"
                }:
                    runtime["state"] = "cancelled"
                    runtime["version"] += 1
                    runtime.pop("gate", None)
            self._json(route, {"success": True})
        elif entry.path.endswith("/runs") and entry.method == "GET":
            if workflow_id in self.workflow_runs:
                self._json(route, {"runs": self.workflow_runs[workflow_id]})
                return
            self._json(route, {"runs": [{
                "id": "run-1",
                "workflow_id": workflow_id,
                "status": "completed_partial",
                "started_at": "2026-09-16T12:00:00Z",
                "workflow_validation": {
                    "version": 1,
                    "status": "accepted_partial",
                    "eligible": True,
                    "reason_codes": ["partial_coverage"],
                    "counts": {"completed": 1, "pending": 1, "failed": 1},
                },
            }]})
        elif entry.path.endswith("/items") and entry.method == "GET":
            self._json(route, {"items": [
                {
                    "id": "doc-item",
                    "item_type": "document",
                    "label": "Skipped document attachment",
                    "status": "completed",
                },
                {
                    "id": "item-1",
                    "item_type": "task",
                    "task_id": "task-a",
                    "label": "Collect evidence",
                    "status": "completed",
                    "workflow_validation": {
                        "version": 1,
                        "status": "valid",
                        "eligible": True,
                        "reason_codes": [],
                        "counts": {"records": 3},
                    },
                    "workflow_result": {
                        "result_ref": {
                            "storage": "cosmos",
                            "schema_version": 1,
                            "sha256": "a" * 64,
                            "size_bytes": 4096,
                            "chunk_count": 2,
                        },
                        "outputs": {"records": {"kind": "records", "result_ref": {
                            "storage": "cosmos", "schema_version": 1, "sha256": "b" * 64,
                            "size_bytes": 4096, "chunk_count": 2,
                        }}},
                        "authoritative_output": "records",
                    },
                    "context_budget": {"used_tokens": 128, "limit": 512},
                },
                {
                    "id": "item-2",
                    "item_type": "task",
                    "task_id": "task-b",
                    "label": "Summarize evidence",
                    "status": "failed",
                    "workflow_validation": {
                        "version": 1,
                        "status": "invalid",
                        "eligible": False,
                        "reason_codes": ["producer_incomplete"],
                        "counts": {"failed": 1},
                    },
                    "workflow_result": {
                        "result_ref": {
                            "storage": "result_store",
                            "schema_version": 1,
                            "sha256": "def456",
                            "size_bytes": 2048,
                            "chunk_count": 1,
                        },
                        "outputs": {"authoritative": {"output_ref": "result://task-b/authoritative"}},
                        "authoritative_output": "authoritative",
                        "consumed_inputs": [{
                            "producer": {"task_id": "task-a", "run_id": "run-1", "attempt": 1},
                            "output_name": "authoritative",
                            "output_ref": "result://task-a/authoritative",
                            "input_name": "Collect_evidence",
                        }],
                    },
                    "consumed_inputs": [{
                        "producer": {"task_id": "task-a", "run_id": "run-1", "attempt": 1},
                        "output_name": "authoritative",
                        "output_ref": "result://task-a/authoritative",
                        "input_name": "Collect_evidence",
                    }],
                    "context_budget": {"used_tokens": 220, "limit": 512},
                },
            ]})
        elif "/tasks/" in entry.path and entry.path.endswith("/result") and entry.method == "GET":
            offset = int(entry.query.get("offset", ["0"])[0])
            output = entry.query.get("output", ["authoritative"])[0]
            content = {
                0: "First transport excerpt page for the authoritative output.",
                2000: "Second transport excerpt page for the authoritative output.",
            }.get(offset, "")
            self._json(route, {
                "content": content,
                "output_name": output,
                "offset": offset,
                "next_offset": 2000 if offset == 0 else None,
                "total_bytes": 3900,
                "complete": offset != 0,
                "sha256": "abc123",
                "integrity": "verified",
            })
        else:
            self.unexpected_requests.append(f"{entry.method} {entry.path}?{entry.query}")
            self._json(route, {"error": "Unsupported workflow route."}, 404)

    def _workflow_runtime(self, route, entry):
        path_parts = entry.path.split("/")
        scope_type = path_parts[2]
        workflow_id = path_parts[4]
        run_id = path_parts[6]
        if scope_type == "group":
            assert entry.query.get("group_id") == [GROUP_ID], entry
        key = (scope_type, workflow_id, run_id)
        runtime = self.workflow_runtimes.get(key)
        if runtime is None:
            self._json(route, {"error": "runtime not found"}, 404)
            return
        if entry.path.endswith("/runtime") and entry.method == "GET":
            self.runtime_get_count[key] = self.runtime_get_count.get(key, 0) + 1
            transition = self.runtime_get_transitions.get(key)
            if transition and self.runtime_get_count[key] >= transition["after_count"]:
                runtime = copy.deepcopy(transition["runtime"])
                self.workflow_runtimes[key] = runtime
                self.runtime_get_transitions.pop(key, None)
                for run in self.workflow_runs.get(workflow_id, []):
                    if run["id"] == run_id:
                        run["status"] = runtime["state"]
            self._json(route, {
                "runtime": copy.deepcopy(runtime),
                "can_decide": self.runtime_can_decide.get(key, True),
            })
            return
        if entry.path.endswith("/runtime/decision") and entry.method == "POST":
            assert isinstance(entry.body, dict), entry
            assert entry.body.get("expected_version") == runtime["version"], entry.body
            assert re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                entry.body.get("request_id", ""),
            ), entry.body
            if self.fail_next_decision_status:
                status = self.fail_next_decision_status
                self.fail_next_decision_status = None
                self.expected_http_errors.add((route.request.url, status))
                self._json(route, {"error": "transient decision failure"}, status)
                return
            if self.stale_next_decision:
                self.stale_next_decision = False
                runtime["version"] += 1
                runtime["gate"] = {
                    "id": "approval-gate-refreshed",
                    "kind": "approval",
                    "unit_id": "approval-task",
                    "input_digest": "sha256:refreshed",
                    "reason": "Approval is still required for the refreshed gate.",
                    "choices": ["approve", "reject"],
                }
                self.expected_http_errors.add((route.request.url, 409))
                self._json(route, {"error": "stale runtime gate"}, 409)
                return
            choice = entry.body["choice"]
            runtime["version"] += 1
            runtime.setdefault("memory", {}).setdefault("decisions", []).append({
                "unit_id": runtime.get("gate", {}).get("unit_id", "approval-task"),
                "choice": choice,
                "actor_user_id": OWNER_ID,
                "decided_at": "2026-09-16T13:01:00Z",
                "input_digest": runtime.get("gate", {}).get("input_digest"),
                "attempt": 1,
            })
            runtime.pop("gate", None)
            runtime["state"] = "queued" if choice in {"approve", "retry", "resume"} else "cancelled"
            for run in self.workflow_runs.get(workflow_id, []):
                if run["id"] == run_id:
                    run["status"] = runtime["state"]
            self._json(route, {
                "runtime": copy.deepcopy(runtime),
                "can_decide": self.runtime_can_decide.get(key, True),
            })
            return
        if entry.path.endswith("/runtime/resume") and entry.method == "POST":
            assert isinstance(entry.body, dict), entry
            assert entry.body.get("expected_version") == runtime["version"], entry.body
            if self.fail_next_resume_status:
                status = self.fail_next_resume_status
                self.fail_next_resume_status = None
                self.expected_http_errors.add((route.request.url, status))
                self._json(route, {"error": "resume rejected"}, status)
                return
            if self.stale_next_resume:
                self.stale_next_resume = False
                runtime["version"] += 1
                runtime["state"] = "failed"
                runtime["can_resume"] = True
                runtime["phase"] = "Recovered checkpoint review"
                runtime["gate"] = {
                    "id": "resume-review-gate",
                    "kind": "recovery",
                    "unit_id": "approval-task",
                    "input_digest": "sha256:resume-refresh",
                    "reason": "Review the refreshed checkpoint before resuming.",
                    "choices": ["retry", "cancel"],
                }
                self.expected_http_errors.add((route.request.url, 409))
                self._json(route, {"error": "stale runtime resume"}, 409)
                return
            runtime["version"] += 1
            runtime["state"] = "queued"
            runtime.pop("gate", None)
            for run in self.workflow_runs.get(workflow_id, []):
                if run["id"] == run_id:
                    run["status"] = "queued"
            self._json(route, {
                "runtime": copy.deepcopy(runtime),
                "can_decide": self.runtime_can_decide.get(key, True),
            })
            return
        self.unexpected_requests.append(f"{entry.method} {entry.path}?{entry.query}")
        self._json(route, {"error": "Unsupported runtime route."}, 404)

    def mutate_revision(self, workflow_id=WORKFLOW_ID):
        self.personal_workflows[workflow_id]["definition_revision"] = "revision:external-change"

    def assert_clean(self):
        super().assert_clean()
        for _, payload in self.responses:
            assert FILE_SYNC_FIXTURE_SECRET not in json.dumps(payload), "A File Sync credential crossed the fixture API boundary."

    def fail_next_workflow_run(self):
        self.fail_next_run = True

    def set_runtime(self, workflow_id, run_id, runtime, can_decide=True, scope_type="user"):
        key = (scope_type, workflow_id, run_id)
        self.workflow_runs[workflow_id] = [{
            "id": run_id,
            "workflow_id": workflow_id,
            "status": runtime["state"],
            "durable_execution": True,
            "started_at": "2026-09-16T12:00:00Z",
        }]
        self.workflow_runtimes[key] = copy.deepcopy(runtime)
        self.runtime_can_decide[key] = can_decide
        self.runtime_get_count[key] = 0
        self.runtime_get_transitions.pop(key, None)

    def transition_runtime_on_get(self, workflow_id, run_id, after_count, runtime, scope_type="user"):
        key = (scope_type, workflow_id, run_id)
        self.runtime_get_transitions[key] = {
            "after_count": after_count,
            "runtime": copy.deepcopy(runtime),
        }

    def stale_next_runtime_decision(self):
        self.stale_next_decision = True

    def fail_next_runtime_decision(self, status=503):
        self.fail_next_decision_status = status

    def stale_next_runtime_resume(self):
        self.stale_next_resume = True

    def fail_next_runtime_resume(self, status=503):
        self.fail_next_resume_status = status


@pytest.fixture
def workflow_ui(page):
    fixture = WorkflowEditorFixture(page)
    yield fixture
    fixture.assert_clean()
