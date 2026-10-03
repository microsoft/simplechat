# test_workflow_handoff_builder.py
#!/usr/bin/env python3
"""
Functional test for the workflow hand-off builder and hand-off drafts.
Version: 0.261.231
Implemented in: 0.261.231

This test ensures that a one-time workflow handed off from chat orchestration:

* builds a durable version 3 For each over the named documents or a bounded workspace query, with
  a current-item Analyze task in its body, a complete Collect and a saved-record report task;
* is always manual, paused and one-time, with no Microsoft 365 or Run as, and alerts to the bell
  on every run at info severity;
* discloses the exact document count, or "up to N" for a query, and respects the loop limits;
* is refused, with stable codes, for unknown handles, unauthorized documents or workspaces, hosted
  agents, disabled analysis, edits that stop being a manual durable workflow, and a record under
  its id that a chat proposal made, and the reverse;
* is created at most once, dry-runs with no write, logs only codes, and its builder imports
  nothing from Flask, Azure or the settings store;
* leaves the Phase 4 blueprint schema, payloads, validation and dry run byte-identical.

Checks use explicit raises, so they hold under ``python -O``.
"""

import copy
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import APP_ROOT, _module  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_draft_save_parity import GROUP_ID, _task, _v2  # noqa: E402
from test_workflow_draft_service import (  # noqa: E402
    DOCUMENT_REVIEW,
    EMAIL_DIGEST,
    EMAIL_HANDLES,
    ORIGIN,
    OWNER_ID,
    PROPOSAL_ID,
    REVIEW_HANDLES,
    USER_INFO,
    DraftHarness,
    _codes,
)


MINIMUM_VERSION = "0.261.231"
HANDOFF_ID = "handoff-1"
HANDOFF_ORIGIN = {**ORIGIN, "proposal_id": HANDOFF_ID}
HANDOFF_WORKFLOW_ID = "481a936e-5e1d-5cc8-a4c9-d8165ded91bf"
PROPOSAL_WORKFLOW_ID = "0c95c5dd-c9b9-59e6-afb8-62068fb72214"
BUILDER_MODULE = "functions_workflow_handoff_builder"

TASKS = [
    {"title": "Review one", "instructions": "Review this contract."},
    {"title": "Report", "instructions": "Write the report."},
]
DOCS = {"name": "Review contracts", "loop": {"source": "documents", "documents": ["doc-a", "doc-b"]}, "tasks": TASKS}
DOC_HANDLES = {"documents": {
    "doc-a": {"document_id": "doc-checklist", "scope_type": "personal", "scope_id": OWNER_ID},
    "doc-b": {"document_id": "doc-team", "scope_type": "group", "scope_id": GROUP_ID},
}}
ALL = {
    "name": "Review all",
    "loop": {
        "source": "workspace_query", "scopes": ["scope-me", "scope-team"], "tags": ["legal"],
        "selection": "all_matches", "content": "indemnity",
    },
    "tasks": TASKS,
}
BEST = {
    "name": "Review best",
    "loop": {
        "source": "workspace_query", "scopes": ["scope-me"], "selection": "best_n", "count": 40,
        "content": "indemnity",
    },
    "tasks": TASKS,
}
SCOPE_HANDLES = {"scopes": {
    "scope-me": {"scope_type": "personal", "scope_id": OWNER_ID},
    "scope-team": {"scope_type": "group", "scope_id": GROUP_ID, "name": "Team"},
}}
AGENT_REVIEW = {
    "name": "Agent review",
    "loop": DOCS["loop"],
    "tasks": [{**TASKS[0], "runner": {"type": "agent", "agent_ref": "reviewer"}}, TASKS[1]],
}
AGENT_HANDLES = {
    **DOC_HANDLES,
    "agents": {"reviewer": {"id": "agent-researcher", "name": "researcher", "is_global": False}},
}

DOCS_ITERABLE = {
    "kind": "documents",
    "documents": [
        {"scope_type": "personal", "document_id": "doc-checklist"},
        {"scope_type": "group", "scope_id": GROUP_ID, "document_id": "doc-team"},
    ],
}
ALL_ITERABLE = {
    "kind": "workspace_query",
    "scopes": [{"scope_type": "personal"}, {"scope_type": "group", "scope_id": GROUP_ID}],
    "filters": {"tags": ["legal"]},
    "selection": {"mode": "all_matches"},
    "content": {"mode": "keyword", "query": "indemnity"},
}
PAUSE_TEXT = (
    "If more match when the run starts, it pauses before reviewing any; "
    "cancel it and ask again with a narrower request."
)
DOCS_DISCLOSURE = {
    "kind": "documents", "count": 2, "limit_behavior": "exact", "text": "2 documents",
    "scope_count": 0, "scope_names": [],
}
ALL_DISCLOSURE = {
    "kind": "workspace_query", "limit": 500, "limit_behavior": "pause",
    "text": f"up to 500 matching documents. {PAUSE_TEXT}",
    "scope_count": 2, "scope_names": ["Your personal workspace", "Team"],
}
BEST_DISCLOSURE = {
    "kind": "workspace_query", "limit": 40, "limit_behavior": "best_n",
    "text": "up to 40 best-matching documents", "scope_count": 1, "scope_names": ["Your personal workspace"],
}
# The editor payload drops these server-owned fields, exactly as the proposal draft read does.
DRAFT_SERVER_FIELDS = frozenset({
    "id", "user_id", "origin", "definition_revision", "created_at", "modified_at", "updated_at",
    "created_by", "modified_by", "status", "last_run_at", "last_run_error", "last_run_response_preview",
    "last_run_started_at", "last_run_status", "last_run_trigger_source", "run_count", "active_run_id",
    "cancellation_requested_at", "cancellation_requested_by", "url_access_authorized",
    "url_access_authorized_at", "url_access_authorized_by", "conversation_id", "next_run_at",
    "m365_binding_approval_id", "m365_revision",
})
RECORDS_SCHEMA = {"type": "array", "items": {"type": "object"}}

# The Phase 4 blueprint schema, payloads, validation and dry run, captured before hand-off existed.
PHASE4_DIGESTS = {
    "schema": "ab12fb1d29c7eaa028a534efa4f610795a31e25638643f30a8ec399b493d9b26",
    "payload_email": "44aced826054039a54ae63588ef6f1a4b5d22447a80d26c2af0f7cfb891739fc",
    "payload_review": "1f93a59c2c6870eaad04a324b4b86262c0f0da6eea745b5a91835b7d0bb73531",
    "validate": "36537c8af7af0882ab7615b0e1014b5eca1181235af439c919ebf7692993197f",
    "dry_review": "3ee5a4afa4c24c08c13f1e10e93128c0995a056bf2f2f158ff9b9af990e771f2",
}
CLOCK_FIELDS = frozenset({"created_at", "modified_at", "updated_at"})
FORBIDDEN_BUILDER_IMPORT = re.compile(
    r"^\s*(from|import)\s+(flask|azure|config|functions_settings|functions_appinsights)\b", re.MULTILINE,
)
PURITY_PROBE = r"""
import json
import socket
import sys

sys.path.insert(0, sys.argv[1])


def _blocked(*args, **kwargs):
    raise OSError("network access is blocked in this probe")


socket.socket.connect = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

import functions_workflow_handoff_builder as builder

blueprint = {
    "name": "Review",
    "loop": {"source": "documents", "documents": ["doc-a"]},
    "tasks": [{"title": "One", "instructions": "Review it."}, {"title": "Report", "instructions": "Report."}],
}
handles = {
    "documents": {"doc-a": {"document_id": "doc-1", "scope_type": "personal", "scope_id": "owner-1"}},
    "scopes": {},
    "agents": {},
}
payload = builder.build_handoff_definition(
    blueprint, handles, workflow_id="wf-1", max_items=1,
    derived_id=lambda workflow_id, kind, key: f"{workflow_id}-{kind}-{key}",
    alert_fields=lambda alerts, workflow_id: {"alert_mode": "rules"},
)
limit = builder.handoff_effective_loop_limit({"workflow_max_loop_items": 500})
if payload["is_enabled"] is not False or payload["m365_run_as_user_id"] != "" or limit != 500:
    raise SystemExit("The builder returned an unexpected payload.")
forbidden = ("flask", "azure", "config", "functions_settings", "functions_appinsights")
print(json.dumps(sorted(name for name in sys.modules if name.split(".")[0] in forbidden)))
"""


def _require(condition, message):
    """Fail even under ``python -O``, which removes assert statements."""
    if not condition:
        raise AssertionError(message)


def _same(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _pairs(errors):
    return [(error["code"], error["path"]) for error in errors]


def _allow_all(scope, actor_user_id=None):
    return True


@pytest.fixture
def harness():
    return DraftHarness()


def _builder(harness):
    return harness.draft_modules[BUILDER_MODULE]


def _options(harness, kwargs):
    return {"origin": HANDOFF_ORIGIN, "settings": harness.settings, "user_info": USER_INFO, **kwargs}


def _dry_run(harness, blueprint, handles, **kwargs):
    return harness.call(
        "dry_run_handoff_workflow", OWNER_ID, copy.deepcopy(blueprint), copy.deepcopy(handles),
        **_options(harness, kwargs),
    )


def _create(harness, blueprint, handles, **kwargs):
    return harness.call(
        "create_personal_handoff_workflow", OWNER_ID, copy.deepcopy(blueprint), copy.deepcopy(handles),
        **_options(harness, kwargs),
    )


def _create_from_payload(harness, payload, **kwargs):
    return harness.call(
        "create_personal_handoff_workflow_from_payload", OWNER_ID, copy.deepcopy(payload),
        **_options(harness, kwargs),
    )


def _check(harness, blueprint, *, settings=None, **kwargs):
    return harness.call(
        "check_handoff_blueprint", copy.deepcopy(blueprint), settings=settings or harness.settings, **kwargs,
    )


def _editor_payload(workflow):
    return {key: value for key, value in workflow.items() if key not in DRAFT_SERVER_FIELDS}


def _task_ids(harness, workflow_id=HANDOFF_WORKFLOW_ID):
    return harness.drafts._derived_id(workflow_id, "task", 0), harness.drafts._derived_id(workflow_id, "task", 1)


def _node_output(name, node_id, output, expected_kind):
    return {
        "name": name,
        "source": {"kind": "node_output", "node_id": node_id, "output": output, "scope": "current"},
        "required": True,
        "expected_kind": expected_kind,
        "allow_partial": False,
    }


def _expected_flow(iterable, max_items, item_id, report_id):
    return {
        "id": "root",
        "nodes": [
            {
                "id": "each",
                "kind": "for_each",
                "inputs": [],
                "iterable": iterable,
                "item_key": "source_identity",
                "max_items": max_items,
                "body": {
                    "id": "body-region",
                    "nodes": [{"id": "body-node", "kind": "task", "task_id": item_id}],
                    "outputs": [_node_output("findings", "body-node", "records", "records")],
                },
            },
            {
                "id": "collect",
                "kind": "collect",
                "source": {"loop_id": "each", "output": "findings"},
                "output_contract": {
                    "kind": "records", "require_complete_coverage": True, "allow_partial": False,
                    "schema": RECORDS_SCHEMA,
                },
            },
            {"id": "report-node", "kind": "task", "task_id": report_id},
        ],
        "outputs": [_node_output("report", "report-node", "text", "text")],
    }


def _expected_item_task(item_id, runner=None):
    return {
        "id": item_id,
        "type": "instructions",
        "order": 1,
        "name": "Review one",
        "instructions": "Review this contract.",
        "runner": runner or {"type": "inherit"},
        "document_action": {
            "type": "analyze", "target_mode": "current_item", "loop_id": "each", "analysis_mode": "combined",
        },
        "inputs": [{
            "name": "item",
            "source": {"kind": "loop_item", "loop_id": "each", "scope": "current"},
            "required": True,
            "expected_kind": "json",
            "allow_partial": False,
        }],
        "reference_ids": [],
        "output_contract": {
            "kind": "records", "require_complete_coverage": False, "allow_partial": False, "schema": RECORDS_SCHEMA,
        },
    }


def _expected_report_task(report_id):
    # The report's ``document_action`` is normalized to many defaults; only its type is checked.
    return {
        "id": report_id,
        "type": "instructions",
        "order": 2,
        "name": "Report",
        "instructions": "Write the report.",
        "runner": {"type": "inherit"},
        "input_processing": "saved_record_report",
        "inputs": [_node_output("findings", "collect", "records", "records")],
        "reference_ids": [],
        "output_contract": {"kind": "text", "require_complete_coverage": False, "allow_partial": False},
    }


def _without_action(task):
    return {key: value for key, value in task.items() if key != "document_action"}


def test_version_includes_the_workflow_handoff_builder():
    assert_app_version_at_least(MINIMUM_VERSION)


def test_named_documents_build_a_durable_version_3_for_each(harness):
    result = _dry_run(harness, DOCS, DOC_HANDLES)
    writes = harness.writes()
    item_id, report_id = _task_ids(harness)
    derived_id = harness.call("orchestration_workflow_id", OWNER_ID, HANDOFF_ID)

    _require(result["ok"] is True, f"The dry run failed: {result['errors']!r}")
    workflow = result["workflow"]
    _same(derived_id, HANDOFF_WORKFLOW_ID, "the derived hand-off workflow id")
    _same(workflow["id"], HANDOFF_WORKFLOW_ID, "the workflow id")
    _same(workflow["definition_version"], 3, "definition_version")
    _require(workflow["durable_execution"] is True, "A hand-off must run durably.")
    _require(workflow["is_enabled"] is False, "A hand-off must be created paused.")
    _same(workflow["trigger_type"], "manual", "trigger_type")
    _same(workflow["m365_run_as_user_id"], "", "m365_run_as_user_id")
    _same(workflow["origin"], {**HANDOFF_ORIGIN, "edited": False, "one_time": True}, "origin")
    _same(workflow["limits"], {"max_executions": 5000, "deadline_seconds": 86400}, "limits")
    _same(workflow["error_handling"], {"strategy": "halt", "retry_count": 0}, "error_handling")
    _same(
        {key: workflow[key] for key in (
            "name", "description", "runner_type", "model_endpoint_id", "model_id", "chat_capabilities_enabled",
            "reference_inputs", "url_access_enabled", "conversation_id", "created_by", "modified_by",
        )},
        {
            "name": "Review contracts", "description": "", "runner_type": "model", "model_endpoint_id": "",
            "model_id": "", "chat_capabilities_enabled": False, "reference_inputs": [], "url_access_enabled": False,
            "conversation_id": "", "created_by": OWNER_ID, "modified_by": OWNER_ID,
        },
        "the workflow fields",
    )
    _same(workflow["flow"], _expected_flow(DOCS_ITERABLE, 2, item_id, report_id), "the flow")
    item_task, report_task = workflow["tasks"]
    _same(item_task, _expected_item_task(item_id), "the per-document task")
    _same(_without_action(report_task), _expected_report_task(report_id), "the report task")
    _same(report_task["document_action"]["type"], "none", "the report task's document action")
    _same(result["disclosure"], DOCS_DISCLOSURE, "the disclosure")
    _same(result["loop_limit"], 2, "the loop limit")
    _same(writes, {}, "the dry run's writes")


def test_a_workspace_query_builds_a_bounded_for_each(harness):
    every = _dry_run(harness, ALL, SCOPE_HANDLES, authorize_scope=_allow_all)
    best = _dry_run(harness, BEST, SCOPE_HANDLES, authorize_scope=_allow_all)
    item_id, report_id = _task_ids(harness)

    _require(every["ok"] is True, f"The query dry run failed: {every['errors']!r}")
    _same(every["workflow"]["flow"], _expected_flow(ALL_ITERABLE, 500, item_id, report_id), "the query flow")
    _same(every["disclosure"], ALL_DISCLOSURE, "the query disclosure")
    _same(every["loop_limit"], 500, "the query loop limit")

    _require(best["ok"] is True, f"The best_n dry run failed: {best['errors']!r}")
    loop = best["workflow"]["flow"]["nodes"][0]
    _same(loop["max_items"], 40, "the best_n item limit")
    _same(loop["iterable"]["selection"], {"mode": "best_n", "count": 40}, "the best_n selection")
    _same(loop["iterable"]["scopes"], [{"scope_type": "personal"}], "the best_n scopes")
    _same(loop["iterable"]["content"], {"mode": "keyword", "query": "indemnity"}, "the best_n content")
    _same(best["disclosure"], BEST_DISCLOSURE, "the best_n disclosure")
    _same(best["loop_limit"], 40, "the best_n loop limit")
    _same(harness.writes(), {}, "the query dry runs' writes")


def test_disclosure_counts_singulars_and_unnamed_workspaces(harness):
    builder = _builder(harness)
    one_document = builder.handoff_disclosure(
        {"loop": {"source": "documents", "documents": ["doc-a"]}}, {}, max_items=1,
    )
    best_one = builder.handoff_disclosure(
        {"loop": {"source": "workspace_query", "scopes": ["g"], "selection": "best_n", "count": 1}},
        {"scopes": {"g": {"scope_type": "group", "scope_id": GROUP_ID}}}, max_items=1,
    )
    every = builder.handoff_disclosure(
        {"loop": {"source": "workspace_query", "scopes": ["p", "pub"], "selection": "all_matches"}},
        {"scopes": {
            "p": {"scope_type": "personal", "scope_id": OWNER_ID},
            "pub": {"scope_type": "public", "scope_id": "public-1"},
        }},
        max_items=1234,
    )

    _same(one_document["text"], "1 document", "one named document")
    _same(one_document["count"], 1, "one named document's count")
    _same(best_one["text"], "up to 1 best-matching document", "one best match")
    _same(best_one["scope_names"], ["A group workspace"], "an unnamed group workspace")
    _same(every["text"], f"up to 1,234 matching documents. {PAUSE_TEXT}", "every match")
    _same(every["scope_names"], ["Your personal workspace", "A public workspace"], "unnamed workspaces")
    _same(every["limit"], 1234, "every match's limit")


def test_the_loop_limit_follows_the_admin_setting_up_to_the_hand_off_bound(harness):
    builder = _builder(harness)
    default_limit = builder.handoff_effective_loop_limit(harness.settings)
    highest = builder.handoff_effective_loop_limit({"workflow_max_loop_items": 5000})
    lowered = builder.handoff_effective_loop_limit({"workflow_max_loop_items": 100})

    _same(builder.HANDOFF_MAX_LOOP_ITEMS, 2000, "the hand-off loop bound")
    _same(default_limit, 500, "the default limit")
    _same(highest, 2000, "the limit under the highest admin setting")
    _same(lowered, 100, "a lowered limit")
    with pytest.raises(ValueError):
        builder.handoff_effective_loop_limit(None)


def test_the_loop_limits_are_enforced(harness):
    too_many = copy.deepcopy(BEST)
    too_many["loop"]["count"] = 2600
    over_admin = copy.deepcopy(BEST)
    over_admin["loop"]["count"] = 600
    many_documents = {"name": "D", "loop": {"source": "documents", "documents": [f"doc-{i}" for i in range(26)]},
                      "tasks": TASKS}
    lowered = {**harness.settings, "workflow_max_loop_items": 100}

    _prepared, bound_errors = _check(harness, too_many)
    _prepared, admin_errors = _check(harness, over_admin)
    _prepared, document_errors = _check(harness, many_documents)
    _prepared, changed_errors = _check(harness, ALL, settings=lowered, loop_limit=500)
    unchanged, unchanged_errors = _check(harness, ALL, loop_limit=500)
    kept = _dry_run(harness, ALL, SCOPE_HANDLES, authorize_scope=_allow_all, loop_limit=100)

    _same(_pairs(bound_errors), [("handoff_loop_limit", "/loop/count")], "a best_n count over the bound")
    _same(_pairs(admin_errors), [("handoff_loop_limit", "/loop")], "a best_n count over the admin limit")
    _same(admin_errors[0]["message"], "One hand-off can cover up to 500 documents.", "the admin limit message")
    _same(_pairs(document_errors), [("handoff_loop_limit", "/loop/documents")], "too many named documents")
    _same(_pairs(changed_errors), [("handoff_limit_changed", "/loop")], "a lowered admin limit")
    _same(unchanged_errors, [], "an unchanged admin limit")
    _require(unchanged is not None, "An unchanged admin limit must pass.")
    _require(kept["ok"] is True, f"A disclosed limit must be kept: {kept['errors']!r}")
    _same(kept["workflow"]["flow"]["nodes"][0]["max_items"], 100, "the kept item limit")
    _same(kept["disclosure"]["limit"], 100, "the kept disclosure limit")
    with pytest.raises(ValueError):
        _check(harness, ALL, loop_limit=0)


def test_alerts_are_notify_only_on_every_run_at_info_severity(harness):
    result = _dry_run(harness, DOCS, DOC_HANDLES)

    _require(result["ok"] is True, f"The dry run failed: {result['errors']!r}")
    workflow = result["workflow"]
    rules = workflow["alert_rules"]
    _same(_builder(harness).HANDOFF_ALERTS, {"mode": "every_run", "severity": "info"}, "the hand-off alerts")
    _same(workflow["alert_mode"], "rules", "alert_mode")
    _same(workflow["alert_priority"], "none", "alert_priority")
    _same(workflow["alert_evaluation"], {"on_error": "skip"}, "alert_evaluation")
    _same([rule["name"] for rule in rules], ["Run completed", "Run had errors"], "the alert rules")
    _same([rule["delivery"] for rule in rules], ["notify_only", "notify_only"], "the alert delivery")
    _same([rule["severity"] for rule in rules], ["info", "low"], "the alert severities")
    _same(
        [rule["condition"] for rule in rules],
        [
            {"type": "run_status", "statuses": ["completed"]},
            {"type": "run_status", "statuses": ["failed", "completed_with_task_errors"]},
        ],
        "the alert conditions",
    )
    _same([rule["scope"] for rule in rules], [{"type": "final", "task_id": ""}] * 2, "the alert scopes")
    _same([rule["enabled"] for rule in rules], [True, True], "the alert rules' enabled flags")


def test_the_blueprint_cannot_name_microsoft_365_run_as_a_trigger_or_a_model(harness):
    refused = {}
    for field, value in (
        ("run_as", "self"), ("trigger", {"type": "manual"}), ("alerts", {"mode": "never"}), ("durable", True),
        ("m365_run_as_user_id", OWNER_ID),
    ):
        _prepared, errors = _check(harness, {**DOCS, field: value})
        refused[field] = _pairs(errors)
    _prepared, model_errors = _check(harness, {**DOCS, "tasks": [{**TASKS[0], "model": "gpt-4o"}, TASKS[1]]})
    _prepared, scope_errors = _check(
        harness, {**DOCS, "loop": {**DOCS["loop"], "scopes": ["scope-me"]}},
    )
    _prepared, task_errors = _check(harness, {**DOCS, "tasks": [*TASKS, TASKS[0]]})
    built = _dry_run(harness, DOCS, DOC_HANDLES)

    for field, pairs in refused.items():
        _same(pairs, [("unsupported_field", f"/{field}")], f"the {field} field")
    _same(_pairs(model_errors), [("unsupported_field", "/tasks/0/model")], "a task model")
    _same(_pairs(scope_errors), [("unsupported_field", "/loop/scopes")], "scopes on a documents loop")
    _same(scope_errors[0]["message"], "This field does not apply here. Remove it.", "the scopes message")
    _same(_pairs(task_errors), [("blueprint_invalid", "/tasks")], "three tasks")
    _same(
        task_errors[0]["message"],
        "A hand-off has exactly two tasks: one that reviews each document and one that writes the report.",
        "the task count message",
    )
    _require(built["ok"] is True, f"The dry run failed: {built['errors']!r}")
    _same(built["workflow"]["m365_run_as_user_id"], "", "the built m365_run_as_user_id")
    _same(built["workflow"]["trigger_type"], "manual", "the built trigger")


def test_a_hand_off_is_created_once_paused_and_one_time(harness):
    first = _create(harness, DOCS, DOC_HANDLES)
    second = _create(harness, DOCS, DOC_HANDLES)
    writes = harness.writes()
    stored = harness.containers["personal_workflows"].items.get((OWNER_ID, HANDOFF_WORKFLOW_ID)) or {}
    other_id = harness.call("orchestration_workflow_id", OWNER_ID, "handoff-2")
    proposal_id = harness.call("orchestration_workflow_id", OWNER_ID, PROPOSAL_ID)

    _require(first["ok"] is True and first["created"] is True, f"The create failed: {first['errors']!r}")
    _require(second["ok"] is True and second["created"] is False, "A repeated create must return the stored one.")
    _same(writes, {"personal_workflows": [("create_item", HANDOFF_WORKFLOW_ID)]}, "the creates' writes")
    _require(stored.get("is_enabled") is False, "The stored hand-off must be paused.")
    _require((stored.get("origin") or {}).get("one_time") is True, "The stored hand-off must be one-time.")
    _require(first["workflow"]["is_enabled"] is False, "The created hand-off must be paused.")
    _same(second["workflow"]["id"], HANDOFF_WORKFLOW_ID, "the repeated create's workflow id")
    _require(other_id != HANDOFF_WORKFLOW_ID, "Another hand-off must get another workflow id.")
    _same(proposal_id, PROPOSAL_WORKFLOW_ID, "the proposal workflow id")
    with harness.active():
        _require(
            harness.drafts.is_handoff_workflow(stored, OWNER_ID) is True, "The stored hand-off must be recognized.",
        )
        _require(harness.drafts.is_handoff_workflow(stored, "other-user") is False, "Another user's must not.")


def test_the_builder_is_deterministic_and_bounded(harness):
    builder = _builder(harness)
    with harness.active():
        drafts = harness.drafts
        prepared, errors = drafts.check_handoff_blueprint(copy.deepcopy(DOCS), settings=harness.settings)
        handles = drafts.normalize_handoff_handles(copy.deepcopy(DOC_HANDLES), user_id=OWNER_ID)
        options = {"workflow_id": HANDOFF_WORKFLOW_ID, "derived_id": drafts._derived_id,
                   "alert_fields": drafts._alert_fields}
        one = builder.build_handoff_definition(copy.deepcopy(prepared), copy.deepcopy(handles), max_items=2, **options)
        two = builder.build_handoff_definition(copy.deepcopy(prepared), copy.deepcopy(handles), max_items=2, **options)
        refused = []
        for max_items in (0, 2001, True, "2"):
            try:
                builder.build_handoff_definition(prepared, handles, max_items=max_items, **options)
            except ValueError:
                refused.append(max_items)
        three_tasks = {**prepared, "tasks": [*prepared["tasks"], prepared["tasks"][0]]}
        with pytest.raises(ValueError):
            builder.build_handoff_definition(three_tasks, handles, max_items=2, **options)

    _same(errors, [], "the checked blueprint")
    _same(json.dumps(one, sort_keys=True), json.dumps(two, sort_keys=True), "two builds")
    _require(one["is_enabled"] is False, "The builder must emit a paused workflow.")
    _same(one["m365_run_as_user_id"], "", "the builder's m365_run_as_user_id")
    _same(one["trigger_type"], "manual", "the builder's trigger")
    _same(refused, [0, 2001, True, "2"], "the refused item limits")


def test_a_hand_off_and_a_chat_proposal_never_share_a_workflow(harness):
    proposal = harness.create(EMAIL_DIGEST, EMAIL_HANDLES)
    over_proposal = _create(harness, DOCS, DOC_HANDLES, origin=dict(ORIGIN))
    payload_over_proposal = _create_from_payload(harness, {"name": "Edited"}, origin=dict(ORIGIN))
    proposal_writes = harness.writes()

    other = DraftHarness()
    handoff = _create(other, DOCS, DOC_HANDLES)
    proposal_over_handoff = other.create(EMAIL_DIGEST, EMAIL_HANDLES, origin=dict(HANDOFF_ORIGIN))
    handoff_writes = other.writes()
    other.containers["personal_workflows"].items[(OWNER_ID, HANDOFF_WORKFLOW_ID)]["deleting"] = True
    deleting = _create(other, DOCS, DOC_HANDLES)

    plain = DraftHarness()
    plain.containers["personal_workflows"].items[(OWNER_ID, HANDOFF_WORKFLOW_ID)] = {
        "id": HANDOFF_WORKFLOW_ID, "user_id": OWNER_ID, "name": "Old",
        "origin": {"source": "orchestration", "proposal_id": HANDOFF_ID},
    }
    not_one_time = _create(plain, DOCS, DOC_HANDLES)

    _require(proposal["ok"] is True and proposal["created"] is True, "The chat proposal must be created.")
    _same(_codes(over_proposal), [("handoff_kind_mismatch", "")], "a hand-off over a chat proposal")
    _same(_codes(payload_over_proposal), [("handoff_kind_mismatch", "")], "an edited hand-off over a proposal")
    _same(proposal_writes, {"personal_workflows": [("create_item", PROPOSAL_WORKFLOW_ID)]}, "the proposal writes")
    _require(handoff["ok"] is True and handoff["created"] is True, "The hand-off must be created.")
    _same(_codes(proposal_over_handoff), [("workflow_conflict", "")], "a chat proposal over a hand-off")
    _same(
        proposal_over_handoff["errors"][0]["message"], "A different workflow already uses this id.",
        "the proposal conflict message",
    )
    _same(handoff_writes, {"personal_workflows": [("create_item", HANDOFF_WORKFLOW_ID)]}, "the hand-off writes")
    _same(_codes(deleting), [("workflow_conflict", "")], "a hand-off being deleted")
    _same(deleting["errors"][0]["message"], "This workflow is being deleted.", "the deleting message")
    _same(_codes(not_one_time), [("handoff_kind_mismatch", "")], "a record that is not one-time")
    _same(plain.writes(), {}, "the refused create's writes")


def test_a_workspace_the_user_cannot_read_is_refused(harness):
    deny_group = _dry_run(
        harness, ALL, SCOPE_HANDLES, authorize_scope=lambda scope, actor_user_id=None: scope["scope_type"] != "group",
    )

    def raising(scope, actor_user_id=None):
        raise PermissionError("denied")

    raised = _dry_run(harness, ALL, SCOPE_HANDLES, authorize_scope=raising)
    unanswered = _dry_run(harness, ALL, SCOPE_HANDLES, authorize_scope=lambda scope, actor_user_id=None: None)
    unknown = _dry_run(harness, ALL, {"scopes": {"scope-me": SCOPE_HANDLES["scopes"]["scope-me"]}},
                       authorize_scope=_allow_all)

    _same(_codes(deny_group), [("scope_unavailable", "/loop/scopes/1")], "a denied group workspace")
    _same(
        _codes(raised), [("scope_unavailable", "/loop/scopes/0"), ("scope_unavailable", "/loop/scopes/1")],
        "an authorizer that raises",
    )
    _require(unanswered["ok"] is True, "Only an explicit denial refuses a workspace.")
    _same(_codes(unknown), [("reference_unknown", "/loop/scopes/1")], "an unknown workspace handle")
    _same(unknown["errors"][0]["message"], "No workspace was provided for this handle.", "the workspace message")


def test_a_document_must_be_named_and_readable(harness):
    missing = _dry_run(harness, DOCS, {"documents": {"doc-a": DOC_HANDLES["documents"]["doc-a"]}})
    unreadable = _dry_run(harness, DOCS, {"documents": {
        **DOC_HANDLES["documents"], "doc-b": {"document_id": "doc-missing", "scope_type": "personal"},
    }})

    _same(_codes(missing), [("reference_unknown", "/loop/documents/1")], "an unknown document handle")
    _same(missing["errors"][0]["message"], "No document was provided for this handle.", "the document message")
    _same(_codes(unreadable), [("reference_unauthorized", "/loop/documents/1")], "an unreadable document")
    with pytest.raises(ValueError):
        _dry_run(harness, DOCS, {"other": {}})


def test_the_handle_map_is_normalized_and_closed(harness):
    with harness.active():
        normalize = harness.drafts.normalize_handoff_handles
        normalized = normalize(
            {"scopes": {"me": {"scope_type": "personal"},
                        "team": {"scope_type": "group", "scope_id": GROUP_ID}}},
            user_id=OWNER_ID,
        )
        refused = []
        for handles in (
            {"other": {}},
            {"scopes": {"Bad Handle": {"scope_type": "personal"}}},
            {"scopes": {"me": {"scope_type": "tenant"}}},
            {"scopes": {"me": {"scope_type": "personal", "extra": True}}},
            "nope",
        ):
            try:
                normalize(handles, user_id=OWNER_ID)
            except ValueError as exc:
                refused.append(str(exc))

    _same(
        normalized,
        {
            "documents": {},
            "scopes": {
                "me": {"scope_type": "personal", "scope_id": OWNER_ID},
                "team": {"scope_type": "group", "scope_id": GROUP_ID},
            },
            "agents": {},
        },
        "the normalized handles",
    )
    _same(refused, ["The workflow draft handle map is malformed."] * 5, "the malformed handle maps")


def test_only_local_agents_may_run_a_hand_off(harness):
    with harness.active():
        sys.modules["functions_agent_delegation"] = _module(
            "functions_agent_delegation",
            resolve_delegation_agent=lambda agent, user_id=None, settings=None: {"agent_type": "local", **agent},
        )
        local = harness.drafts.dry_run_handoff_workflow(
            OWNER_ID, copy.deepcopy(AGENT_REVIEW), copy.deepcopy(AGENT_HANDLES), **_options(harness, {}),
        )
    original = harness.personal.get_personal_agents
    harness.personal.get_personal_agents = lambda user_id: [{
        "id": "agent-researcher", "name": "researcher", "display_name": "R", "description": "",
        "is_enabled": True, "agent_type": "aifoundry",
    }]
    try:
        hosted = _dry_run(harness, AGENT_REVIEW, AGENT_HANDLES)
    finally:
        harness.personal.get_personal_agents = original
    unknown = _dry_run(harness, AGENT_REVIEW, {
        **DOC_HANDLES, "agents": {"reviewer": {"id": "agent-gone", "name": "gone", "is_global": False}},
    })

    _require(local["ok"] is True, f"A local agent must be accepted: {local['errors']!r}")
    _same(
        local["workflow"]["tasks"][0]["runner"],
        {"type": "agent", "selected_agent": {
            "id": "agent-researcher", "name": "researcher", "display_name": "Researcher",
            "description": "Finds facts.", "is_global": False, "is_group": False,
        }},
        "the local agent runner",
    )
    _same(_codes(hosted), [("handoff_agent_unsupported", "/tasks/0/runner/agent_ref")], "a hosted agent")
    _same(_codes(unknown), [("agent_unavailable", "/tasks/0/runner/agent_ref")], "an unknown agent")


def test_a_hand_off_needs_analysis_two_tasks_and_workflows():
    no_analysis = DraftHarness()
    no_analysis.settings["document_action_capabilities"] = {"analyze": {"enabled": False}}
    one_task = DraftHarness()
    one_task.settings["workflow_max_tasks"] = 1
    no_workflows = DraftHarness()
    no_workflows.settings["allow_user_workflows"] = False

    analysis_result = _dry_run(no_analysis, DOCS, DOC_HANDLES)
    task_result = _dry_run(one_task, DOCS, DOC_HANDLES)
    workflow_result = _dry_run(no_workflows, DOCS, DOC_HANDLES)
    create_result = _create(no_workflows, DOCS, DOC_HANDLES)

    _same(_codes(analysis_result), [("handoff_analyze_unavailable", "/loop")], "analysis turned off")
    _same(_codes(task_result), [("handoff_unavailable", "/tasks")], "a one-task limit")
    _same(_codes(workflow_result), [("workflows_unavailable", "")], "workflows turned off")
    _require(
        workflow_result["disclosure"] is None and workflow_result["loop_limit"] is None,
        "A refused dry run must disclose nothing.",
    )
    _same(_codes(create_result), [("workflows_unavailable", "")], "a create with workflows turned off")
    _same(no_workflows.writes(), {}, "the refused writes")


def test_an_edited_hand_off_stays_a_paused_manual_durable_workflow(harness):
    dry = _dry_run(harness, DOCS, DOC_HANDLES)
    _require(dry["ok"] is True, f"The dry run failed: {dry['errors']!r}")
    draft = _editor_payload(dry["workflow"])

    as_is = _create_from_payload(harness, draft)
    repeated = _create_from_payload(harness, draft)
    as_is_writes = harness.writes()

    forged_harness = DraftHarness()
    forged = _create_from_payload(forged_harness, {
        **draft, "name": "Edited", "is_enabled": True, "one_time": False, "origin": {"source": "x"},
        "conversation_id": "conv-other",
    })
    forged_stored = forged_harness.containers["personal_workflows"].items[(OWNER_ID, HANDOFF_WORKFLOW_ID)]

    refusals = {}
    refused_harness = DraftHarness()
    for label, payload in (
        ("interval", {**draft, "trigger_type": "interval", "schedule": {"unit": "hours", "value": 1}}),
        ("not_durable", {**draft, "durable_execution": False}),
        ("plain", _v2("Plain", tasks=[_task("t1", "T", "Do it.")])),
        ("run_as", {**draft, "m365_run_as_user_id": OWNER_ID}),
        ("version_2", {**draft, "definition_version": 2}),
        ("url_access", {**draft, "url_access_enabled": True}),
        ("other_id", {**draft, "id": "other"}),
    ):
        refusals[label] = _codes(_create_from_payload(refused_harness, payload))

    _require(as_is["ok"] is True and as_is["created"] is True, f"The edited create failed: {as_is['errors']!r}")
    _require(repeated["ok"] is True and repeated["created"] is False, "A repeated edit must not create again.")
    _same(as_is_writes, {"personal_workflows": [("create_item", HANDOFF_WORKFLOW_ID)]}, "the edited writes")
    workflow = as_is["workflow"]
    _require(workflow["is_enabled"] is False, "An edited hand-off must be paused.")
    _require(workflow["origin"]["one_time"] is True, "An edited hand-off must be one-time.")
    _same(workflow["conversation_id"], "", "the edited conversation_id")
    _same((workflow["created_by"], workflow["modified_by"]), (OWNER_ID, OWNER_ID), "the edited actors")

    _require(forged["ok"] is True, f"A forged edit must still be created: {forged['errors']!r}")
    _require(forged_stored["is_enabled"] is False, "A forged is_enabled must be ignored.")
    _require(forged_stored["origin"]["one_time"] is True, "A forged one_time must be ignored.")
    _same(forged_stored["origin"]["proposal_id"], HANDOFF_ID, "the forged origin")
    _same(forged_stored["conversation_id"], "", "the forged conversation_id")
    _same(forged_stored["name"], "Edited", "the edited name")

    _same(refusals, {
        "interval": [("handoff_edit_invalid", "/trigger_type")],
        "not_durable": [("invalid_workflow_definition", "")],
        "plain": [("handoff_edit_invalid", "/durable_execution")],
        "run_as": [("handoff_edit_invalid", "/m365_run_as_user_id")],
        "version_2": [("invalid_workflow", "")],
        "url_access": [("unsupported_field", "/url_access_enabled")],
        "other_id": [("workflow_conflict", "/id")],
    }, "the refused edits")
    _same(refused_harness.writes(), {}, "the refused edits' writes")


def test_a_dry_run_writes_nothing_on_an_executor_thread(harness):
    def dry_runs():
        return (
            _dry_run(harness, DOCS, DOC_HANDLES),
            _dry_run(harness, ALL, SCOPE_HANDLES, authorize_scope=_allow_all),
        )

    with harness.guarded(), ThreadPoolExecutor(max_workers=1) as executor:
        documents, query = executor.submit(dry_runs).result()

    _require(documents["ok"] is True, f"The documents dry run failed: {documents['errors']!r}")
    _require(query["ok"] is True, f"The query dry run failed: {query['errors']!r}")
    _same(harness.writes(), {}, "the guarded dry runs' writes")


def test_logs_carry_codes_and_never_ids_or_text(harness):
    events = []
    original = harness.drafts.log_event

    def record(message, extra=None, level=None, **kwargs):
        events.append({"message": message, "extra": copy.deepcopy(extra)})

    harness.drafts.log_event = record
    try:
        _dry_run(harness, DOCS, DOC_HANDLES)
        _dry_run(harness, DOCS, {"documents": {"doc-a": DOC_HANDLES["documents"]["doc-a"]}})
        _create(harness, DOCS, DOC_HANDLES)
    finally:
        harness.drafts.log_event = original

    handoff_events = [event for event in events if event["message"].startswith("[WorkflowHandoffDrafts]")]
    _same(
        [event["message"] for event in handoff_events],
        [
            "[WorkflowHandoffDrafts] dry_run accepted",
            "[WorkflowHandoffDrafts] dry_run rejected",
            "[WorkflowHandoffDrafts] create accepted",
        ],
        "the hand-off log messages",
    )
    _same(
        [event["extra"] for event in handoff_events],
        [
            {"operation": "dry_run", "created": False, "error_codes": []},
            {"operation": "dry_run", "created": False, "error_codes": ["reference_unknown"]},
            {"operation": "create", "created": True, "error_codes": []},
        ],
        "the hand-off log fields",
    )
    logged = json.dumps(events)
    for secret in (
        OWNER_ID, GROUP_ID, HANDOFF_ID, HANDOFF_WORKFLOW_ID, "doc-checklist", "doc-team", "doc-a", "doc-b",
        "Review contracts", "Review this contract.", "conv-chat", "run-1",
    ):
        _require(secret not in logged, f"A log carried {secret!r}.")


def test_the_builder_imports_nothing_from_flask_azure_or_settings():
    source = (APP_ROOT / f"{BUILDER_MODULE}.py").read_text(encoding="utf-8")
    loaded = {}
    for label, flags in (("normal", []), ("optimized", ["-O"])):
        completed = subprocess.run(
            [sys.executable, "-B", *flags, "-c", PURITY_PROBE, str(APP_ROOT)],
            capture_output=True, text=True, timeout=180, check=False,
        )
        _require(completed.returncode == 0, f"The {label} purity probe failed: {completed.stderr[-2000:]}")
        loaded[label] = json.loads(completed.stdout.strip().splitlines()[-1])

    _require(FORBIDDEN_BUILDER_IMPORT.search(source) is None, "The builder imports an application service.")
    _require(re.search(r"\bflask\.(request|session|current_app|g)\b", source) is None, "The builder reads Flask.")
    _same(loaded, {"normal": [], "optimized": []}, "the modules the builder loads")


def test_the_phase_4_blueprint_and_payloads_are_unchanged(harness):
    with harness.active():
        drafts = harness.drafts
        digests = {"schema": _digest(drafts.WORKFLOW_BLUEPRINT_SCHEMA)}
        for label, blueprint, handles in (
            ("email", EMAIL_DIGEST, EMAIL_HANDLES), ("review", DOCUMENT_REVIEW, REVIEW_HANDLES),
        ):
            payload = drafts.build_workflow_blueprint_payload(
                copy.deepcopy(blueprint), copy.deepcopy(handles),
                workflow_id=drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID), user_id=OWNER_ID,
                settings=harness.settings,
            )
            digests[f"payload_{label}"] = _digest(payload)
        invalid = [
            {"name": "x"},
            dict(EMAIL_DIGEST, loop={"source": "documents"}),
            dict(EMAIL_DIGEST, tasks=[]),
            "not a dict",
        ]
        digests["validate"] = _digest([drafts.validate_workflow_blueprint(copy.deepcopy(item)) for item in invalid])
    fresh = DraftHarness()
    with fresh.active():
        result = fresh.drafts.dry_run_workflow_blueprint(
            OWNER_ID, copy.deepcopy(DOCUMENT_REVIEW), copy.deepcopy(REVIEW_HANDLES), origin=ORIGIN,
            settings=fresh.settings, user_info=USER_INFO,
        )
    workflow = result["workflow"]
    digests["dry_review"] = _digest({
        "ok": result["ok"],
        "errors": result["errors"],
        "workflow": {key: value for key, value in workflow.items() if key not in CLOCK_FIELDS} if workflow else None,
    })

    _same(digests, PHASE4_DIGESTS, "the Phase 4 digests")


def test_the_hand_off_schema_is_closed_and_separate(harness):
    with harness.active():
        schema = harness.drafts.workflow_handoff_blueprint_schema()
        schema["title"] = "changed"
        again = harness.drafts.workflow_handoff_blueprint_schema()
        phase4 = harness.drafts.WORKFLOW_BLUEPRINT_SCHEMA

    Draft202012Validator.check_schema(again)
    _same(again["$id"], "urn:simplechat:workflow-handoff-blueprint:1", "the hand-off schema id")
    _same(again["title"], "Workflow hand-off blueprint", "a copy of the hand-off schema")
    _require(again["additionalProperties"] is False, "The hand-off schema must be closed.")
    _same(sorted(again["properties"]), ["description", "loop", "name", "tasks"], "the hand-off fields")
    _require("loop" not in phase4["properties"], "The Phase 4 schema must not gain a loop.")


def test_the_loop_preview_reads_the_built_for_each(harness):
    builder = _builder(harness)
    result = _dry_run(harness, DOCS, DOC_HANDLES)
    _require(result["ok"] is True, f"The dry run failed: {result['errors']!r}")
    preview = builder.handoff_loop_preview(result["workflow"])
    preview["iterable"]["documents"].clear()

    _same(builder.handoff_loop_preview(result["workflow"]), {"iterable": DOCS_ITERABLE, "max_items": 2}, "the preview")
    _require(builder.handoff_loop_preview({}) is None, "A workflow without a flow has no preview.")
    _require(builder.handoff_loop_preview(None) is None, "No workflow has no preview.")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
