# test_workflow_draft_save_parity.py
#!/usr/bin/env python3
"""
Functional test for workflow save parity across the workflow draft service refactor.
Version: 0.261.197
Implemented in: 0.261.197

This test ensures that ``save_personal_workflow`` and ``save_group_workflow`` behave byte for byte
as they did before each save was split into a write-free build step and a persist step.

The golden file ``fixtures/workflow_save_parity_golden.json`` was captured from the unrefactored
code, the Phase 1 head (c5a375f06), by running this file with ``--capture``. Each scenario replays
saves through the real personal and group workflow modules over doubled I/O. For each save it
records:

* the returned document's SHA-256 over ``json.dumps`` without sorting, and its key order, so a
  changed value or a reordered key both show up;
* the stored Cosmos item's SHA-256 and every container write;
* every dependency call, in order: settings and user-settings reads, agent and model endpoint
  lookups, File Sync source reads, group role checks and shared-reference authorization;
* the error type, message and code of a refused save.

The clock and ``uuid.uuid4`` are deterministic counters, so a change in the number or order of
timestamp or identifier draws also shows up as a difference. The scenarios cover manual,
interval, calendar and File Sync triggers, alert modes, shared references, agent and model
runners, Microsoft 365 Run as approval state, legacy v1 workflows and version 3 definitions.
"""

import argparse
import copy
import hashlib
import itertools
import json
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

# The shared real-module harness helpers live beside the group round-trip test.
from test_group_workflow_round_trip_preservation import (  # noqa: E402
    APP_ROOT,
    WorkflowContainer,
    _document_analysis_seams,
    _file_sync_constant,
    _installed,
    _load,
    _module,
)


GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "workflow_save_parity_golden.json"
MINIMUM_VERSION = "0.261.197"

OWNER_ID = "owner-1"
EDITOR_ID = "admin-2"
MEMBER_ID = "member-3"
GROUP_ID = "group-alpha"
PUBLIC_WORKSPACE_ID = "public-1"
CLOCK_START = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)

GLOBAL_ENDPOINT = {
    "id": "endpoint-global", "name": "Global AOAI", "provider": "aoai", "enabled": True,
    "models": [{"id": "model-4o", "deploymentName": "gpt-4o", "modelName": "gpt-4o", "enabled": True}],
}
PERSONAL_ENDPOINT = {
    "id": "endpoint-personal", "name": "My AOAI", "provider": "aoai", "enabled": True,
    "models": [{"id": "model-mini", "deploymentName": "gpt-4o-mini", "enabled": True}],
}
GROUP_ENDPOINT = {
    "id": "endpoint-group", "name": "Team AOAI", "provider": "aoai", "enabled": True,
    "models": [{"id": "model-team", "deploymentName": "gpt-4.1", "enabled": True}],
}
SETTINGS = {
    "workflow_max_tasks": 50,
    "workflow_min_schedule_interval_seconds": 300,
    "enable_semantic_kernel": True,
    "allow_user_agents": True,
    "allow_group_agents": True,
    "allow_user_custom_endpoints": True,
    "allow_group_custom_endpoints": True,
    "model_endpoints": [GLOBAL_ENDPOINT],
    "azure_openai_gpt_deployment": "gpt-4o",
    "gpt_model": {"selected": [{"deploymentName": "gpt-4o", "modelName": "gpt-4o"}]},
}
PERSONAL_AGENTS = [
    {"id": "agent-researcher", "name": "researcher", "display_name": "Researcher",
     "description": "Finds facts.", "is_enabled": True},
    {"id": "agent-writer", "name": "writer", "display_name": "Writer", "description": "Writes.", "is_enabled": True},
]
GROUP_AGENTS = [
    {"id": "agent-analyst", "name": "analyst", "display_name": "Analyst",
     "description": "Analyzes team data.", "is_enabled": True},
]
GLOBAL_AGENTS = [
    {"id": "agent-global", "name": "global_helper", "display_name": "Global helper",
     "description": "Shared helper.", "is_enabled": True},
]
# A save imports these lazily; they are tracked so a call never leaves one installed afterwards.
LAZY_MODULES = ("functions_workflow_execution", "functions_agent_delegation")
# Real modules, in import-graph order. The structured-flow modules are loaded here because a version
# 3 save imports them lazily and the application folder is not on this test's import path.
REAL_MODULES = (
    "functions_workflow_alert_safety", "functions_workflow_definitions", "functions_workflow_alerts",
    "functions_m365_workflow_binding", "functions_workflow_definition_store", "functions_document_actions",
    "functions_workflow_limits", "functions_workflow_schedules",
    "functions_workflow_loop_schema", "functions_workflow_flow", "functions_workflow_identity",
    "functions_workflow_loop_runners",
    "functions_personal_workflows", "functions_group_workflow_policy", "functions_group_workflows",
)


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SaveParityHarness:
    """The real personal and group workflow stores over recorded, deterministic I/O."""

    def __init__(self):
        self.settings = copy.deepcopy(SETTINGS)
        self.calls = []
        self.steps = []
        self.containers = {
            "personal_workflows": WorkflowContainer("user_id"),
            "group_workflows": WorkflowContainer("group_id"),
            "conversations": WorkflowContainer("id"),
        }
        self.containers["conversations"].items.update({
            ("conv-personal", "conv-personal"): {
                "id": "conv-personal", "chat_type": "workflow", "user_id": OWNER_ID, "_etag": '"c1"',
            },
            ("conv-group", "conv-group"): {
                "id": "conv-group", "chat_type": "workflow", "user_id": OWNER_ID, "group_id": GROUP_ID,
                "_etag": '"c2"',
            },
            ("conv-chat", "conv-chat"): {"id": "conv-chat", "chat_type": "personal", "user_id": OWNER_ID},
        })
        self.roles = {
            (GROUP_ID, OWNER_ID): "Owner",
            (GROUP_ID, EDITOR_ID): "Admin",
            (GROUP_ID, MEMBER_ID): "User",
        }
        self.file_sync_groups = {GROUP_ID}
        self.sources = {
            ("personal", OWNER_ID, "my-share"): {
                "id": "my-share", "name": "My share", "source_type": "smb", "auth": {"password": "never-store"},
            },
            ("group", GROUP_ID, "finance-share"): {
                "id": "finance-share", "name": "Finance share", "source_type": "sharepoint",
            },
        }
        self.user_settings = {
            OWNER_ID: {"id": OWNER_ID, "settings": {"personal_model_endpoints": [PERSONAL_ENDPOINT]}},
        }
        self.group_endpoints = {GROUP_ID: [GROUP_ENDPOINT]}
        self.forbidden_documents = {"forbidden-doc"}
        self._clock = itertools.count()
        self._uuids = itertools.count(1)
        self.stubs = self._build_stubs()
        with _installed((*self.stubs, *REAL_MODULES)):
            sys.modules.update(self.stubs)
            self.modules = {name: _load(name, APP_ROOT / f"{name}.py") for name in REAL_MODULES}
        self.personal = self.modules["functions_personal_workflows"]
        self.group = self.modules["functions_group_workflows"]
        self.personal._utc_now = self._now

    def _now(self):
        return CLOCK_START + timedelta(seconds=next(self._clock))

    def _record(self, *call):
        self.calls.append(json.loads(json.dumps(list(call), default=str)))

    def _build_stubs(self):
        def get_settings():
            self._record("get_settings")
            return copy.deepcopy(self.settings)

        def get_user_settings(user_id, *args, **kwargs):
            self._record("get_user_settings", user_id, list(args), sorted(kwargs))
            return copy.deepcopy(self.user_settings.get(user_id) or {"id": user_id, "settings": {}})

        def assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin")):
            self._record("assert_group_role", user_id, group_id, list(allowed_roles))
            role = self.roles.get((group_id, user_id))
            if not role:
                raise PermissionError("User is not a member of this group")
            if role.lower() not in {allowed.lower() for allowed in allowed_roles}:
                raise PermissionError("Insufficient permissions for this group")
            return role

        def get_group_model_endpoints(group_id):
            self._record("get_group_model_endpoints", group_id)
            return copy.deepcopy(self.group_endpoints.get(group_id) or [])

        def get_authorized_sync_source(scope_type, source_id, user_id, scope_id=None, **kwargs):
            self._record("get_authorized_sync_source", scope_type, scope_id, source_id, user_id, sorted(kwargs))
            if scope_type == "group":
                assert_group_role(user_id, scope_id, allowed_roles=("Owner", "Admin"))
            source = self.sources.get((scope_type, scope_id, source_id))
            if source is None:
                raise LookupError("File sync source not found")
            return copy.deepcopy(source)

        def sanitize_file_sync_source(source):
            sanitized = dict(source or {})
            sanitized.pop("auth", None)
            return sanitized

        def is_file_sync_enabled_for_group(settings, group_id, user_info=None):
            self._record("is_file_sync_enabled_for_group", group_id, user_info)
            return group_id in self.file_sync_groups

        def get_personal_agents(user_id):
            self._record("get_personal_agents", user_id)
            return copy.deepcopy(PERSONAL_AGENTS)

        def get_group_agents(group_id):
            self._record("get_group_agents", group_id)
            return copy.deepcopy(GROUP_AGENTS)

        def get_global_agents():
            self._record("get_global_agents")
            return copy.deepcopy(GLOBAL_AGENTS)

        def require_model_capability(model_cfg, provider=None, **kwargs):
            self._record("require_model_capability", model_cfg.get("id"), provider, sorted(kwargs))

        def authorize_workflow_reference(workflow, reference, **kwargs):
            self._record(
                "authorize_workflow_reference", workflow, reference,
                kwargs.get("actor_user_id"), sorted(kwargs),
            )
            if reference.get("document_id") in self.forbidden_documents:
                raise PermissionError("A shared reference is not available in the selected source scope.")
            return {"scope": reference.get("scope_type"), "document": {"id": reference.get("document_id")}}

        config_module = _module(
            "config",
            cosmos_personal_workflows_container=self.containers["personal_workflows"],
            cosmos_group_workflows_container=self.containers["group_workflows"],
            cosmos_conversations_container=self.containers["conversations"],
            cosmos_personal_workflow_runs_container=WorkflowContainer("user_id"),
            cosmos_personal_workflow_run_items_container=WorkflowContainer("run_id"),
            cosmos_group_workflow_runs_container=WorkflowContainer("group_id"),
            cosmos_group_workflow_run_items_container=WorkflowContainer("run_id"),
        )
        return {
            "config": config_module,
            "functions_appinsights": _module(
                "functions_appinsights", log_event=lambda *args, **kwargs: None,
                debug_print=lambda *args, **kwargs: None, is_debug_enabled=lambda *args, **kwargs: False,
            ),
            "functions_debug": _module("functions_debug", debug_print=lambda *args, **kwargs: None),
            "functions_settings": _module(
                "functions_settings", get_settings=get_settings, get_user_settings=get_user_settings,
                normalize_model_endpoints=lambda endpoints: (copy.deepcopy(list(endpoints or [])), False),
            ),
            "functions_file_sync": _module(
                "functions_file_sync",
                FILE_SYNC_SCOPE_GROUP=_file_sync_constant("FILE_SYNC_SCOPE_GROUP"),
                FILE_SYNC_SCOPE_PERSONAL=_file_sync_constant("FILE_SYNC_SCOPE_PERSONAL"),
                FILE_SYNC_SCOPE_PUBLIC=_file_sync_constant("FILE_SYNC_SCOPE_PUBLIC"),
                get_authorized_sync_source=get_authorized_sync_source,
                sanitize_file_sync_source=sanitize_file_sync_source,
                is_file_sync_enabled_for_group=is_file_sync_enabled_for_group,
            ),
            "functions_group": _module(
                "functions_group", assert_group_role=assert_group_role,
                get_group_model_endpoints=get_group_model_endpoints,
            ),
            "functions_ai_connections": _module(
                "functions_ai_connections", require_model_capability=require_model_capability,
            ),
            "functions_global_agents": _module("functions_global_agents", get_global_agents=get_global_agents),
            "functions_personal_agents": _module("functions_personal_agents", get_personal_agents=get_personal_agents),
            "functions_group_agents": _module("functions_group_agents", get_group_agents=get_group_agents),
            "functions_workflow_result_store": _module("functions_workflow_result_store"),
            "functions_workflow_bindings": _module(
                "functions_workflow_bindings", authorize_workflow_reference=authorize_workflow_reference,
            ),
            "functions_workflow_runtime_store": _module("functions_workflow_runtime_store"),
            "functions_workflow_execution": _module(
                "functions_workflow_execution", current_workflow_execution=lambda: None,
            ),
            **_document_analysis_seams(),
        }

    @contextmanager
    def active(self):
        """Install the doubles for one call, so lazy imports resolve to them, then remove them."""
        original_uuid4 = uuid.uuid4
        uuid.uuid4 = lambda: uuid.UUID(int=next(self._uuids))
        try:
            with _installed((*self.stubs, *REAL_MODULES, *LAZY_MODULES)):
                sys.modules.update(self.stubs)
                sys.modules.update(self.modules)
                yield
        finally:
            uuid.uuid4 = original_uuid4

    def _step(self, label, container_name, partition, operation):
        call_start = len(self.calls)
        write_start = {name: len(container.writes) for name, container in self.containers.items()}
        result = None
        error = None
        try:
            with self.active():
                result = operation()
        except Exception as exc:  # The golden records refusals exactly as raised.
            error = {
                "type": type(exc).__name__,
                "message": str(exc),
                "code": getattr(exc, "code", None),
            }
        record = {
            "label": label,
            "error": error,
            "calls": self.calls[call_start:],
            "writes": {
                name: [list(write) for write in container.writes[write_start[name]:]]
                for name, container in self.containers.items()
                if container.writes[write_start[name]:]
            },
        }
        if result is not None:
            encoded = json.dumps(result)
            stored = self.containers[container_name].items.get((partition, result.get("id")))
            record.update({
                "result_sha256": _digest(encoded),
                "result_keys": list(result),
                "stored_sha256": _digest(json.dumps(stored)) if stored is not None else None,
                "summary": {
                    key: result.get(key) for key in (
                        "id", "name", "trigger_type", "schedule", "next_run_at", "is_enabled",
                        "definition_version", "alert_mode", "m365_run_as_user_id",
                        "m365_binding_approval_id", "conversation_id", "modified_by",
                    )
                },
            })
        self.steps.append(record)
        return result

    def save_personal(self, label, payload, actor_user_id=None):
        def operation():
            if actor_user_id is None:
                return self.personal.save_personal_workflow(OWNER_ID, copy.deepcopy(payload))
            return self.personal.save_personal_workflow(OWNER_ID, copy.deepcopy(payload), actor_user_id=actor_user_id)
        return self._step(label, "personal_workflows", OWNER_ID, operation)

    def save_group(self, label, payload, actor_user_id=OWNER_ID, user_info=None):
        def operation():
            return self.group.save_group_workflow(
                GROUP_ID, copy.deepcopy(payload), actor_user_id=actor_user_id,
                user_info=user_info if user_info is not None else {"roles": ["User"]},
            )
        return self._step(label, "group_workflows", GROUP_ID, operation)

    def load_personal(self, workflow_id):
        with self.active():
            return self.personal.get_personal_workflow(OWNER_ID, workflow_id)

    def load_group(self, workflow_id):
        with self.active():
            return self.group.get_group_workflow(GROUP_ID, workflow_id)

    def seed_approval(self, container_name, partition, workflow_id, approval_id):
        """Record an approval the way the approval service does: directly on the stored item."""
        stored = self.containers[container_name].items[(partition, workflow_id)]
        stored["m365_binding_approval_id"] = approval_id


def _task(identifier, name, instructions, **extra):
    task = {
        "id": identifier, "type": "instructions", "name": name, "instructions": instructions,
        "runner": {"type": "inherit"}, "document_action": {"type": "none"},
    }
    task.update(extra)
    return task


def _v2(name, **fields):
    payload = {
        "name": name, "description": "", "definition_version": 2, "durable_execution": True,
        "runner_type": "model", "model_endpoint_id": "", "model_id": "", "trigger_type": "manual",
        "chat_capabilities_enabled": False, "reference_inputs": [],
    }
    payload.update(fields)
    return payload


CALENDAR_WEEKLY = {
    "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"],
    "time_of_day": "08:00", "timezone": "America/New_York",
}
CALENDAR_DAILY = {"kind": "calendar", "frequency": "daily", "time_of_day": "07:30", "timezone": "Europe/London"}
DIGEST_RULES = [
    {"name": "Run completed", "severity": "info", "delivery": "notify_only",
     "condition": {"type": "run_status", "statuses": ["completed"]}},
    {"name": "A task failed", "severity": "low", "scope": {"type": "any_task"},
     "condition": {"type": "task_status", "statuses": ["failed"]}},
]


# Personal scenarios --------------------------------------------------------------------------

def personal_manual_v2(h):
    created = h.save_personal("create", _v2(
        "Weekly planning", description="Plan the week.",
        tasks=[
            {"name": "Gather", "instructions": "List this week's meetings.", "runner": {"type": "inherit"}},
            {"name": "Summarize", "instructions": "Summarize them.", "runner": {"type": "inherit"},
             "document_action": {"type": "none"}},
        ],
    ))
    edited = h.save_personal("describe", {**created, "description": "Plan the whole week."}, actor_user_id=OWNER_ID)
    h.save_personal("resave", h.load_personal(edited["id"]), actor_user_id=OWNER_ID)


def personal_interval_every_run(h):
    created = h.save_personal("create", _v2(
        "Queue check", trigger_type="interval", schedule={"unit": "hours", "value": 2}, is_enabled=True,
        alert_mode="every_run", alert_priority="medium", chat_capabilities_enabled=True,
        url_access_enabled=True, url_access_authorized=True, url_access_authorized_by=OWNER_ID,
        url_access_authorized_at="2026-09-01T00:00:00+00:00",
        error_handling={"strategy": "continue", "retry_count": 2},
        tasks=[_task("check", "Check", "Check the queue.")],
    ))
    h.save_personal("reschedule", {**created, "schedule": {"unit": "hours", "value": 3}})
    h.save_personal("disable", {**h.load_personal(created["id"]), "is_enabled": False})
    h.save_personal("enable", {**h.load_personal(created["id"]), "is_enabled": True})
    h.save_personal("create_disabled", _v2(
        "Paused check", trigger_type="interval", schedule={"unit": "minutes", "value": 45}, is_enabled=False,
        tasks=[_task("check", "Check", "Check the paused queue.")],
    ))


def personal_calendar_rules(h):
    created = h.save_personal("create", _v2(
        "Monday digest", trigger_type="interval", schedule=CALENDAR_WEEKLY, alert_mode="rules",
        alert_rules=copy.deepcopy(DIGEST_RULES),
        tasks=[_task("read", "Read", "Read my email."), _task("list", "List", "List this week's to-dos.")],
    ))
    h.save_personal("retime", {
        **created, "schedule": {**CALENDAR_WEEKLY, "days_of_week": ["monday", "thursday"], "time_of_day": "09:15"},
    })
    h.save_personal("resave", h.load_personal(created["id"]))


def personal_file_sync_calendar(h):
    h.save_personal("create", _v2(
        "Contract watcher", trigger_type="file_sync", schedule=CALENDAR_DAILY, is_enabled=True,
        file_sync={
            "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
            "sources": [{"scope_type": "personal", "source_id": "my-share"}],
        },
        tasks=[_task("review", "Review", "Review each changed contract.",
                     document_action={"type": "analyze", "document_ids": [], "analysis_mode": "per_document"})],
    ))


def personal_manual_file_sync_defaults(h):
    created = h.save_personal("create", _v2(
        "Sync then read", file_sync={"enabled": True, "sources": [{"scope_type": "personal", "source_id": "my-share"}]},
        tasks=[_task("read", "Read", "Read the synced files.")],
    ))
    h.save_personal("resave", h.load_personal(created["id"]))
    h.save_personal("missing_source", _v2(
        "Gone", file_sync={"enabled": True, "sources": [{"scope_type": "personal", "source_id": "deleted-share"}]},
        tasks=[_task("read", "Read", "Read the synced files.")],
    ))


def personal_file_sync_group_source_interval(h):
    created = h.save_personal("create", _v2(
        "Finance watcher", trigger_type="file_sync", schedule={"unit": "minutes", "value": 30},
        file_sync={
            "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": False,
            "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}],
        },
        tasks=[_task("summarize", "Summarize", "Summarize what changed.")],
    ))
    h.save_personal("resave", h.load_personal(created["id"]))


def personal_references(h):
    created = h.save_personal("create", _v2(
        "Policy review",
        reference_inputs=[
            {"id": "policy", "name": "policy", "document_id": "doc-policy", "scope_type": "personal"},
            {"id": "handbook", "name": "handbook", "document_id": "doc-handbook",
             "scope_type": "public", "scope_id": PUBLIC_WORKSPACE_ID},
        ],
        tasks=[_task("compare", "Compare", "Compare the policy with the handbook.",
                     reference_ids=["policy", "handbook"])],
    ))
    h.save_personal("resave", h.load_personal(created["id"]), actor_user_id=OWNER_ID)
    h.save_personal("forbidden", _v2(
        "Forbidden reference",
        reference_inputs=[{"id": "secret", "name": "secret", "document_id": "forbidden-doc", "scope_type": "personal"}],
        tasks=[_task("use", "Use", "Use the reference.", reference_ids=["secret"])],
    ))


def personal_agents_and_overrides(h):
    created = h.save_personal("create", _v2(
        "Research and write", runner_type="agent",
        selected_agent={"id": "agent-researcher", "name": "researcher", "is_global": False},
        tasks=[
            _task("research", "Research", "Research the topic."),
            _task("write", "Write", "Write it up.",
                  runner={"type": "agent", "selected_agent": {"id": "agent-writer", "name": "writer"}}),
            _task("polish", "Polish", "Polish the text.",
                  runner={"type": "model", "model_endpoint_id": "endpoint-personal", "model_id": "model-mini"}),
        ],
    ))
    h.save_personal("resave", h.load_personal(created["id"]))
    h.save_personal("global_agent", _v2(
        "Global helper", runner_type="agent",
        selected_agent={"id": "agent-global", "name": "global_helper", "is_global": True},
        tasks=[_task("help", "Help", "Help with the request.")],
    ))


def personal_custom_model(h):
    h.save_personal("create", _v2(
        "Custom model", model_endpoint_id="endpoint-global", model_id="model-4o",
        tasks=[_task("answer", "Answer", "Answer the question.")],
    ))
    h.save_personal("unknown_endpoint", _v2(
        "Missing endpoint", model_endpoint_id="endpoint-gone", model_id="model-4o",
        tasks=[_task("answer", "Answer", "Answer the question.")],
    ))


def personal_m365_run_as(h):
    created = h.save_personal("create", _v2(
        "Mail digest", m365_run_as_user_id=OWNER_ID,
        tasks=[_task("mail", "Mail", "Summarize my unread mail.")],
    ))
    h.seed_approval("personal_workflows", OWNER_ID, created["id"], "approval-1")
    loaded = h.load_personal(created["id"])
    kept = h.save_personal("describe_keeps_approval", {**loaded, "description": "Morning summary."})
    h.save_personal("task_change_clears_approval", {
        **h.load_personal(kept["id"]),
        "tasks": [_task("mail", "Mail", "Summarize my unread and flagged mail.")],
    })


def personal_v1_classic(h):
    created = h.save_personal("create", {
        "name": "Classic", "task_prompt": "Say hello.", "runner_type": "model", "trigger_type": "manual",
        "conversation_id": "conv-personal", "alert_priority": "low",
    })
    h.save_personal("resave", h.load_personal(created["id"]))
    h.save_personal("classic_update", {
        "id": created["id"], "name": "Classic renamed", "task_prompt": "Say hello twice.", "runner_type": "model",
        "trigger_type": "manual", "conversation_id": "conv-personal",
    })
    h.save_personal("chat_conversation", {
        "name": "Wrong conversation", "task_prompt": "Say hello.", "runner_type": "model",
        "trigger_type": "manual", "conversation_id": "conv-chat",
    })


def personal_v3_structured(h):
    created = h.save_personal("create", _v2(
        "Structured", definition_version=3,
        tasks=[_task("gather", "Gather", "Gather the facts.", inputs=[], output_contract={"kind": "text"})],
        flow={"id": "root", "nodes": [{"id": "gather_node", "kind": "task", "task_id": "gather"}], "outputs": []},
    ))
    h.save_personal("resave", h.load_personal(created["id"]))


def personal_errors(h):
    task = [_task("one", "One", "Do one thing.")]
    h.save_personal("missing_trigger", {**_v2("No trigger", tasks=task), "trigger_type": ""})
    h.save_personal("unknown_trigger", _v2("Webhook", trigger_type="webhook", tasks=task))
    h.save_personal("file_sync_without_sources", _v2("No sync", trigger_type="file_sync",
                                                     schedule={"unit": "hours", "value": 1}, tasks=task))
    h.save_personal("rules_without_rules", _v2("No rules", alert_mode="rules", alert_rules=[], tasks=task))
    h.save_personal("below_minimum", _v2("Too often", trigger_type="interval",
                                         schedule={"unit": "minutes", "value": 1}, tasks=task))
    h.save_personal("bad_timezone", _v2("Mars", trigger_type="interval",
                                        schedule={**CALENDAR_WEEKLY, "timezone": "Mars/Olympus"}, tasks=task))
    h.save_personal("unknown_kind", _v2("Cron", trigger_type="interval",
                                        schedule={"kind": "cron", "expression": "* * * * *"}, tasks=task))
    h.save_personal("missing_runner", {**_v2("No runner", tasks=task), "runner_type": ""})
    h.save_personal("too_many_tasks", _v2("Big", tasks=[
        _task(f"task-{index}", f"Task {index}", "Work.") for index in range(51)
    ]))
    created = h.save_personal("create", _v2("Stale", tasks=task))
    h.save_personal("stale_revision", {**created, "definition_revision": "0" * 64, "description": "Late edit."})
    h.save_personal("deleted", {**created, "id": "missing-workflow"})
    h.settings["enable_semantic_kernel"] = False
    h.save_personal("agents_disabled", _v2("Agents off", runner_type="agent",
                                           selected_agent={"id": "agent-researcher"}, tasks=task))


# Group scenarios -----------------------------------------------------------------------------

def group_manual_v2(h):
    created = h.save_group("create", _v2(
        "Team planning", description="Plan the team week.",
        tasks=[{"name": "Gather", "instructions": "List the team's meetings.", "runner": {"type": "inherit"}}],
    ))
    h.save_group("editor_describes", {**created, "description": "Plan the sprint."}, actor_user_id=EDITOR_ID)
    h.save_group("resave", h.load_group(created["id"]), actor_user_id=OWNER_ID)


def group_interval_every_run(h):
    created = h.save_group("create", _v2(
        "Team queue", trigger_type="interval", schedule={"unit": "hours", "value": 6},
        alert_mode="every_run", alert_priority="high", tasks=[_task("check", "Check", "Check the team queue.")],
    ))
    h.save_group("disable", {**h.load_group(created["id"]), "is_enabled": False})


def group_calendar_rules(h):
    created = h.save_group("create", _v2(
        "Team digest", trigger_type="interval",
        schedule={"kind": "calendar", "frequency": "monthly", "day_of_month": 31, "time_of_day": "17:00",
                  "timezone": "Australia/Sydney"},
        alert_mode="rules", alert_rules=copy.deepcopy(DIGEST_RULES),
        tasks=[_task("close", "Close", "Summarize the month.")],
    ))
    h.save_group("resave", h.load_group(created["id"]))


def group_file_sync_calendar(h):
    created = h.save_group("create", _v2(
        "Finance drops", trigger_type="file_sync",
        schedule={"kind": "calendar", "frequency": "weekdays", "time_of_day": "06:00", "timezone": "UTC"},
        file_sync={
            "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
            "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}],
        },
        tasks=[_task("review", "Review", "Review each changed file.",
                     document_action={"type": "analyze", "document_ids": [], "analysis_mode": "per_document"})],
    ), user_info={"roles": ["User"], "groups": [GROUP_ID]})
    h.save_group("editor_resave", h.load_group(created["id"]), actor_user_id=EDITOR_ID)


def group_references(h):
    created = h.save_group("create", _v2(
        "Team policy",
        reference_inputs=[{"id": "policy", "name": "policy", "document_id": "doc-team-policy",
                           "scope_type": "group", "scope_id": GROUP_ID}],
        tasks=[_task("check", "Check", "Check against the policy.", reference_ids=["policy"])],
    ))
    h.save_group("editor_resave", h.load_group(created["id"]), actor_user_id=EDITOR_ID)


def group_agents_and_overrides(h):
    created = h.save_group("create", _v2(
        "Team analysis", runner_type="agent",
        selected_agent={"id": "agent-analyst", "name": "analyst", "is_global": False},
        tasks=[
            _task("analyze", "Analyze", "Analyze the data."),
            _task("report", "Report", "Report on it.",
                  runner={"type": "agent", "selected_agent": {"id": "agent-analyst", "name": "analyst"}}),
            _task("tidy", "Tidy", "Tidy the report.",
                  runner={"type": "model", "model_endpoint_id": "endpoint-group", "model_id": "model-team"}),
        ],
    ))
    h.save_group("resave", h.load_group(created["id"]))


def group_m365_run_as(h):
    created = h.save_group("create", _v2(
        "Team mail", m365_run_as_user_id=EDITOR_ID, tasks=[_task("mail", "Mail", "Summarize the team inbox.")],
    ), actor_user_id=EDITOR_ID)
    h.seed_approval("group_workflows", GROUP_ID, created["id"], "approval-group")
    kept = h.save_group("describe_keeps_approval", {**h.load_group(created["id"]), "description": "Daily."},
                        actor_user_id=EDITOR_ID)
    h.save_group("task_change_clears_approval", {
        **h.load_group(kept["id"]), "tasks": [_task("mail", "Mail", "Summarize and triage the team inbox.")],
    }, actor_user_id=EDITOR_ID)


def group_v1_classic(h):
    created = h.save_group("create", {
        "name": "Team classic", "task_prompt": "Say hello to the team.", "runner_type": "model",
        "trigger_type": "manual", "conversation_id": "conv-group",
    })
    h.save_group("resave", h.load_group(created["id"]))
    h.save_group("classic_update", {
        "id": created["id"], "name": "Team classic renamed", "task_prompt": "Say hello again.",
        "runner_type": "model", "trigger_type": "manual", "conversation_id": "conv-group",
    })


def group_v3_structured(h):
    created = h.save_group("create", _v2(
        "Team structured", definition_version=3,
        tasks=[_task("gather", "Gather", "Gather the team facts.", inputs=[], output_contract={"kind": "text"})],
        flow={"id": "root", "nodes": [{"id": "gather_node", "kind": "task", "task_id": "gather"}], "outputs": []},
    ), actor_user_id=EDITOR_ID)
    h.save_group("owner_resave", h.load_group(created["id"]), actor_user_id=OWNER_ID)


def group_errors(h):
    task = [_task("one", "One", "Do one thing.")]
    h.save_group("missing_trigger", {**_v2("No trigger", tasks=task), "trigger_type": ""})
    h.save_group("member_task_runner", _v2("Member", tasks=[
        _task("one", "One", "Do one thing.",
              runner={"type": "model", "model_endpoint_id": "endpoint-global", "model_id": "model-4o"}),
    ]), actor_user_id=MEMBER_ID)
    h.save_group("unknown_kind", _v2("Cron", trigger_type="interval",
                                     schedule={"kind": "cron"}, tasks=task))
    h.save_group("other_group_source", _v2(
        "Other group", trigger_type="file_sync", schedule={"unit": "hours", "value": 1},
        file_sync={"enabled": True, "wait_mode": "complete", "continue_mode": "changed",
                   "sources": [{"scope_type": "group", "scope_id": "group-beta", "source_id": "x"}]},
        tasks=task,
    ))
    h.save_group("personal_reference", _v2(
        "Personal ref",
        reference_inputs=[{"id": "mine", "name": "mine", "document_id": "doc-1", "scope_type": "personal"}],
        tasks=task,
    ))
    h.file_sync_groups.discard(GROUP_ID)
    h.save_group("file_sync_disabled", _v2(
        "No group sync", trigger_type="file_sync", schedule={"unit": "hours", "value": 1},
        file_sync={"enabled": True, "wait_mode": "complete", "continue_mode": "changed",
                   "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}]},
        tasks=task,
    ))
    h.settings["allow_group_agents"] = False
    h.save_group("group_agents_disabled", _v2("Agents off", runner_type="agent",
                                              selected_agent={"id": "agent-analyst"}, tasks=task))


SCENARIOS = {
    function.__name__: function
    for function in (
        personal_manual_v2, personal_interval_every_run, personal_calendar_rules, personal_file_sync_calendar,
        personal_manual_file_sync_defaults, personal_file_sync_group_source_interval, personal_references, personal_agents_and_overrides,
        personal_custom_model, personal_m365_run_as, personal_v1_classic, personal_v3_structured,
        personal_errors,
        group_manual_v2, group_interval_every_run, group_calendar_rules, group_file_sync_calendar,
        group_references, group_agents_and_overrides, group_m365_run_as, group_v1_classic, group_v3_structured,
        group_errors,
    )
}


def run_scenario(name):
    harness = SaveParityHarness()
    SCENARIOS[name](harness)
    return harness.steps


def _load_golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_every_scenario_has_a_golden():
    """No scenario may be added or dropped without recapturing the golden from base code."""
    assert sorted(_load_golden()) == sorted(SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_save_matches_the_pre_refactor_golden(name):
    """Every save in the scenario returns, stores, calls and refuses exactly as before."""
    expected = _load_golden()[name]
    actual = run_scenario(name)
    assert len(actual) == len(expected), f"{name}: step count changed"
    for index, (got, want) in enumerate(zip(actual, expected)):
        assert got == want, f"{name} step {index} ({want.get('label')}) differs from the pre-refactor golden"


def test_the_golden_exercises_the_real_save_rules():
    """Anti-vacuity: the golden holds real successes and reviewed refusals, not empty records."""
    golden = _load_golden()
    steps = [step for scenario in golden.values() for step in scenario]
    successes = [step for step in steps if step["error"] is None]
    refusals = [step for step in steps if step["error"] is not None]
    assert len(successes) >= 35 and len(refusals) >= 15
    assert all(step["result_sha256"] and step["stored_sha256"] for step in successes)
    codes = {step["error"]["code"] for step in refusals}
    assert {"invalid_workflow_settings", "invalid_workflow_alerts", "workflow_definition_conflict",
            "workflow_deleted", "invalid_workflow_definition"} <= codes
    called = {call[0] for step in steps for call in step["calls"]}
    assert {"authorize_workflow_reference", "get_user_settings", "get_personal_agents", "get_group_agents",
            "get_authorized_sync_source", "assert_group_role", "is_file_sync_enabled_for_group",
            "get_group_model_endpoints", "require_model_capability", "get_settings"} <= called
    approvals = [
        step["summary"]["m365_binding_approval_id"] for step in golden["personal_m365_run_as"] if step["error"] is None
    ]
    assert approvals == [None, "approval-1", None]


def test_version_contract():
    assert_app_version_at_least(MINIMUM_VERSION)


def assert_app_version_at_least(version):
    from test_support.versioning import assert_app_version_at_least as check

    check(version)


def capture():
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    golden = {name: run_scenario(name) for name in sorted(SCENARIOS)}
    GOLDEN_PATH.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Captured {sum(len(steps) for steps in golden.values())} steps into {GOLDEN_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Record the golden from the code in this worktree.")
    arguments = parser.parse_args()
    if arguments.capture:
        capture()
        sys.exit(0)
    sys.exit(pytest.main([__file__, "-q"]))
