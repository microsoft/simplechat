# test_workflow_draft_service.py
#!/usr/bin/env python3
"""
Functional test for the workflow draft service.
Version: 0.261.197
Implemented in: 0.261.197

This test ensures that a workflow blueprint proposed from chat:

* validates against a closed Draft 2020-12 schema that has no free-form destinations, endpoints,
  URLs, models, secrets or raw document ids, with bounded strings and lists;
* dry-runs through the real personal workflow build with no Cosmos write, no conversation access
  and no Flask context, including on an executor thread;
* is rejected, when invalid or forbidden, with one stable, repairable code per problem and a JSON
  pointer, never echoing the caller's input;
* builds deterministically, with digest alerts delivered to the bell and File Sync defaults;
* is created at most once per proposal, within the per-user cap and the schedule minimum for
  workflows created from chat, which leave every other workflow unaffected.

The real workflow modules run over the recorded, deterministic doubles of the save parity test.
"""

import copy
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from jsonschema import Draft202012Validator

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import (  # noqa: E402
    APP_ROOT,
    WorkflowContainer,
    _compiled,
    _installed,
    _load,
    _module,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_draft_save_parity import (  # noqa: E402
    GROUP_ID,
    OWNER_ID,
    SaveParityHarness,
    _task,
    _v2,
)


MINIMUM_VERSION = "0.261.197"
PROPOSAL_ID = "proposal-1"
ORIGIN = {
    "source": "orchestration",
    "conversation_id": "conv-chat",
    "orchestration_run_id": "run-1",
    "proposal_id": PROPOSAL_ID,
    "created_at": "2026-09-28T12:00:00+00:00",
}
USER_INFO = {"roles": ["User"]}
DRAFT_MODULES = ("content_screening", "content_screening.contracts", "functions_workflow_drafts")
WRITE_METHODS = frozenset({
    "create_item", "replace_item", "upsert_item", "delete_item", "patch_item", "execute_item_batch",
})

EMAIL_DIGEST = {
    "name": "Weekly to-do digest",
    "description": "Every Monday, list this week's to-dos from my email.",
    "trigger": {
        "type": "calendar", "frequency": "weekly", "days_of_week": ["monday"],
        "time_of_day": "08:00", "timezone": "America/New_York",
    },
    "tasks": [{
        "title": "List this week's to-dos",
        "instructions": "Read my email from the past week and list the to-dos I need to finish this week.",
        "runner": {"type": "agent", "agent_ref": "mail_agent"},
    }],
    "alerts": {"mode": "every_run", "severity": "info"},
    "run_as": "self",
    "durable": True,
}
EMAIL_HANDLES = {"agents": {"mail_agent": {"id": "agent-researcher", "name": "researcher", "is_global": False}}}

DOCUMENT_REVIEW = {
    "name": "Contract review",
    "trigger": {
        "type": "file_sync", "source_ids": ["contracts"],
        "schedule": {"kind": "calendar", "frequency": "weekdays", "time_of_day": "07:00", "timezone": "Europe/London"},
    },
    "tasks": [
        {
            "title": "Review changed contracts",
            "instructions": "Compare each changed contract against the checklist and list any gaps.",
            "inputs": ["checklist"],
        },
        {"title": "Summarize the gaps", "instructions": "Summarize the gaps for the legal team."},
    ],
    "alerts": {"mode": "failures_only"},
}
REVIEW_HANDLES = {
    "documents": {"checklist": {"document_id": "doc-checklist", "scope_type": "personal"}},
    "sources": {"contracts": {"scope_type": "personal", "source_id": "my-share"}},
}


class CountingWorkflowContainer(WorkflowContainer):
    """A workflow container double that also answers the orchestration count query."""

    def query_items(self, query=None, parameters=None, partition_key=None, **kwargs):
        if query and "COUNT(1)" in query:
            values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
            return iter([sum(
                1 for (partition, _), record in self.items.items()
                if partition == partition_key
                and (record.get("origin") or {}).get("source") == values.get("@source")
                and record.get("deleting") is not True
            )])
        return super().query_items(query=query, parameters=parameters, partition_key=partition_key, **kwargs)


class WriteGuard:
    """Wraps a container so a write, or any access at all when ``forbid_access``, fails the test."""

    def __init__(self, name, inner, forbid_access=False):
        self._name = name
        self._inner = inner
        self._forbid_access = forbid_access

    def __getattr__(self, attribute):
        if self._forbid_access or attribute in WRITE_METHODS:
            raise AssertionError(f"A dry run called {self._name}.{attribute}.")
        return getattr(self._inner, attribute)


class DraftHarness(SaveParityHarness):
    """The save parity harness, plus the draft service and the seams it reads through."""

    def __init__(self):
        self.personal_file_sync_enabled = True
        self.documents = {
            ("personal", OWNER_ID, "doc-checklist"): {"id": "doc-checklist", "user_id": OWNER_ID},
            ("group", GROUP_ID, "doc-team"): {"id": "doc-team", "group_id": GROUP_ID},
        }
        super().__init__()
        self.settings.update({
            "allow_user_workflows": True,
            "workflow_min_schedule_interval_seconds": 300,
            "document_action_capabilities": {"analyze": {"enabled": True}},
        })
        with _installed((*self.stubs, *DRAFT_MODULES, "functions_analysis_access")):
            sys.modules.update(self.stubs)
            sys.modules.update(self.modules)
            # The draft checks use the real reference authorizer, so its read-only resolver seam is
            # exercised. The workflow build keeps the recorded authorizer of the save parity harness.
            sys.modules["functions_analysis_access"] = _module(
                "functions_analysis_access", build_analysis_access=lambda *args, **kwargs: {},
            )
            _load("functions_workflow_bindings", APP_ROOT / "functions_workflow_bindings.py")
            contracts = _load("content_screening.contracts", APP_ROOT / "content_screening" / "contracts.py")
            drafts = _load("functions_workflow_drafts", APP_ROOT / "functions_workflow_drafts.py")
        self.draft_modules = {"content_screening.contracts": contracts, "functions_workflow_drafts": drafts}
        self.contracts = contracts
        self.drafts = drafts

    def _build_stubs(self):
        self.containers["personal_workflows"] = CountingWorkflowContainer("user_id")
        stubs = super()._build_stubs()
        settings_helpers = _compiled(
            APP_ROOT / "functions_settings.py",
            (
                "WORKFLOW_USER_APP_ROLE", "normalize_app_role_claims", "has_workflow_user_app_role",
                "is_user_workflows_enabled_for_user",
            ),
            {},
        )

        def read_user_settings_snapshot(user_id, allow_cross_user=False):
            self._record("read_user_settings_snapshot", user_id, allow_cross_user)
            return copy.deepcopy(self.user_settings.get(user_id) or {"id": user_id, "settings": {}})

        def is_file_sync_enabled_for_user(settings, user_id, user_email=None, user_info=None):
            self._record("is_file_sync_enabled_for_user", user_id, user_info)
            return self.personal_file_sync_enabled

        def is_file_sync_enabled_for_public_workspace(settings, public_workspace_id, user_info=None):
            self._record("is_file_sync_enabled_for_public_workspace", public_workspace_id, user_info)
            return False

        def resolve_document_context(**arguments):
            # The shape ``authorize_workflow_reference`` reads, for documents this harness stores.
            self._record("resolve_document_context", arguments)
            scope = arguments.get("doc_scope")
            scope_id = {
                "personal": arguments.get("user_id"),
                "group": (arguments.get("active_group_ids") or [""])[0],
            }.get(scope, "")
            document = self.documents.get((scope, scope_id, arguments.get("document_id")))
            if document is None:
                return None
            return {"scope": scope, "document": copy.deepcopy(document), "group_id": document.get("group_id")}

        stubs["functions_settings"].read_user_settings_snapshot = read_user_settings_snapshot
        stubs["functions_settings"].is_user_workflows_enabled_for_user = (
            settings_helpers["is_user_workflows_enabled_for_user"]
        )
        stubs["functions_file_sync"].is_file_sync_enabled_for_user = is_file_sync_enabled_for_user
        stubs["functions_file_sync"].is_file_sync_enabled_for_public_workspace = (
            is_file_sync_enabled_for_public_workspace
        )
        stubs["content_screening"] = _module("content_screening")
        stubs["functions_search_service"] = _module(
            "functions_search_service", resolve_document_context=resolve_document_context,
        )
        stubs["functions_public_workspaces"] = _module(
            "functions_public_workspaces",
            visible_public_workspace_ids_from_user_settings=lambda user_settings, list_public_workspaces=None: [],
        )
        self.resolve_document_context = resolve_document_context
        return stubs

    @contextmanager
    def active(self):
        with _installed(DRAFT_MODULES):
            with super().active():
                sys.modules.update(self.draft_modules)
                yield

    def call(self, name, *args, **kwargs):
        """Call a draft service function with the doubles installed."""
        with self.active():
            return getattr(self.drafts, name)(*args, **kwargs)

    def dry_run(self, blueprint, handles=None, **kwargs):
        options = {"origin": ORIGIN, "settings": self.settings, "user_info": USER_INFO, **kwargs}
        handles = {} if handles is None else handles
        return self.call("dry_run_workflow_blueprint", OWNER_ID, copy.deepcopy(blueprint), handles, **options)

    def create(self, blueprint, handles=None, **kwargs):
        options = {"origin": ORIGIN, "settings": self.settings, "user_info": USER_INFO, **kwargs}
        handles = {} if handles is None else handles
        return self.call(
            "create_personal_workflow_from_blueprint", OWNER_ID, copy.deepcopy(blueprint), handles, **options,
        )

    def writes(self):
        return {name: list(container.writes) for name, container in self.containers.items() if container.writes}

    def called(self, name):
        return [call for call in self.calls if call[0] == name]

    @contextmanager
    def guarded(self):
        """Fail on any container write, and on any conversation access, in the workflow modules."""
        replaced = []
        for module in (self.personal, self.group):
            for attribute, value in list(vars(module).items()):
                if attribute.startswith("cosmos_") and attribute.endswith("_container"):
                    replaced.append((module, attribute, value))
                    setattr(module, attribute, WriteGuard(
                        attribute, value, forbid_access=attribute == "cosmos_conversations_container",
                    ))
        try:
            yield
        finally:
            for module, attribute, value in replaced:
                setattr(module, attribute, value)


@pytest.fixture
def harness():
    return DraftHarness()


def _codes(result):
    return [(error["code"], error["path"]) for error in result["errors"]]


def _blueprint(**overrides):
    blueprint = copy.deepcopy(EMAIL_DIGEST)
    blueprint.update(overrides)
    return blueprint


def _tasks(count):
    return [{"title": f"Task {index}", "instructions": f"Do step {index}."} for index in range(count)]


FORBIDDEN_PROPERTY_NAMES = frozenset({
    "url", "urls", "endpoint", "endpoint_id", "model", "model_id", "model_endpoint_id", "deployment",
    "deployment_name", "document_id", "document_ids", "secret", "api_key", "key", "password", "destination",
    "recipient", "recipients", "to", "email", "webhook", "connection_string", "workflow_id", "id",
})


def _subschemas(schema):
    if isinstance(schema, dict):
        yield schema
        for value in schema.values():
            yield from _subschemas(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _subschemas(value)


def test_version_is_at_least_the_draft_service_release():
    assert_app_version_at_least(MINIMUM_VERSION)


def test_the_blueprint_schema_is_closed_bounded_draft_2020_12(harness):
    schema = harness.drafts.WORKFLOW_BLUEPRINT_SCHEMA
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    property_names = set()
    for subschema in _subschemas(schema):
        if subschema.get("type") == "object":
            assert subschema.get("additionalProperties") is False, subschema
        if subschema.get("type") == "array":
            assert isinstance(subschema.get("maxItems"), int), subschema
        if subschema.get("type") == "string":
            assert "maxLength" in subschema or "pattern" in subschema, subschema
        if isinstance(subschema.get("properties"), dict):
            property_names.update(subschema["properties"])
    assert not property_names & FORBIDDEN_PROPERTY_NAMES
    assert schema["properties"]["tasks"]["maxItems"] == 5
    assert schema["properties"]["durable"] == {"const": True}
    assert schema["properties"]["run_as"] == {"enum": ["self", "none"]}

    copied = harness.drafts.workflow_blueprint_schema()
    copied["properties"].clear()
    assert harness.drafts.WORKFLOW_BLUEPRINT_SCHEMA["properties"], "The schema accessor must return a copy."


def test_the_weekly_email_digest_example_dry_runs_with_zero_writes(harness):
    result = harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES)

    assert result["ok"] is True, result["errors"]
    assert result["errors"] == []
    workflow = result["workflow"]
    assert workflow["id"] == harness.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID)
    assert workflow["trigger_type"] == "interval"
    assert workflow["schedule"] == {
        "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "day_of_month": None,
        "time_of_day": "08:00", "timezone": "America/New_York",
    }
    assert workflow["is_enabled"] is False and workflow["next_run_at"] is None
    assert workflow["definition_version"] == 2 and workflow["durable_execution"] is True
    assert workflow["chat_capabilities_enabled"] is False
    assert workflow["m365_run_as_user_id"] == OWNER_ID
    assert workflow["origin"] == {**ORIGIN, "edited": False}
    [task] = workflow["tasks"]
    assert task["runner"]["type"] == "agent"
    assert task["runner"]["selected_agent"]["id"] == "agent-researcher"
    assert harness.writes() == {}
    # Settings arrive with the call, and user settings are read without repairing them.
    assert not harness.called("get_settings")
    assert not harness.called("get_user_settings")


def test_the_file_sync_document_review_example_dry_runs_with_zero_writes(harness):
    result = harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES)

    assert result["ok"] is True, result["errors"]
    workflow = result["workflow"]
    assert workflow["trigger_type"] == "file_sync"
    assert workflow["schedule"]["frequency"] == "weekdays"
    [reference] = workflow["reference_inputs"]
    assert reference["name"] == "checklist" and reference["document_id"] == "doc-checklist"
    assert workflow["tasks"][0]["reference_ids"] == [reference["id"]]
    assert workflow["tasks"][1]["reference_ids"] == []
    assert harness.writes() == {}
    # The draft check resolved the document through the read-only seam, as the requesting user.
    [resolved] = harness.called("resolve_document_context")
    assert resolved[1]["document_id"] == "doc-checklist" and resolved[1]["user_id"] == OWNER_ID


def test_a_dry_run_writes_nothing_and_never_touches_conversations_even_on_an_executor_thread(harness):
    with harness.guarded(), ThreadPoolExecutor(max_workers=1) as executor:
        results = [
            executor.submit(harness.dry_run, EMAIL_DIGEST, EMAIL_HANDLES).result(),
            executor.submit(harness.dry_run, DOCUMENT_REVIEW, REVIEW_HANDLES).result(),
            executor.submit(harness.dry_run, _blueprint(name=""), EMAIL_HANDLES).result(),
        ]
    assert [result["ok"] for result in results] == [True, True, False]
    assert harness.writes() == {}
    assert all(container.writes == [] for container in harness.containers.values())


def test_the_draft_service_needs_no_flask_context():
    source = (APP_ROOT / "functions_workflow_drafts.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+flask\b", source, re.MULTILINE)
    for name in ("request", "session", "current_app", "g"):
        assert not re.search(rf"\bflask\.{name}\b|from flask import[^\n]*\b{name}\b", source)


def test_the_default_document_resolver_reads_through_the_search_service_seam(harness):
    with harness.active():
        resolver = harness.drafts.read_only_document_resolver(
            user_settings_reader=lambda user_id: {"id": user_id, "settings": {}},
        )
        first = resolver(document_id="doc-checklist", user_id=OWNER_ID, doc_scope="personal", include_content=False)
        second = resolver(document_id="doc-checklist", user_id=OWNER_ID, doc_scope="personal", include_content=False)
    assert first == second and first["document"]["id"] == "doc-checklist"
    first["document"]["id"] = "changed"
    assert second["document"]["id"] == "doc-checklist", "The resolver must hand out copies."
    assert len(harness.called("resolve_document_context")) == 1, "The resolver must memoize per draft."


def test_blueprint_invalid_covers_shape_bounds_and_non_json_input(harness):
    validate = harness.drafts.validate_workflow_blueprint
    nested = {"deeper": None}
    for _ in range(20):
        nested = {"deeper": nested}
    cases = {
        "not an object": ([EMAIL_DIGEST], [("blueprint_invalid", "")]),
        "missing name": ({k: v for k, v in EMAIL_DIGEST.items() if k != "name"}, [("blueprint_invalid", "/name")]),
        "blank name": (_blueprint(name="   "), [("blueprint_invalid", "/name")]),
        "121-character name": (_blueprint(name="n" * 121), [("blueprint_invalid", "/name")]),
        "no tasks": (_blueprint(tasks=[]), [("blueprint_invalid", "/tasks")]),
        "4,001-character instructions": (
            _blueprint(tasks=[{"title": "Too long", "instructions": "i" * 4001}]),
            [("blueprint_invalid", "/tasks/0/instructions")],
        ),
        "durable false": (_blueprint(durable=False), [("blueprint_invalid", "/durable")]),
        "unknown run as": (_blueprint(run_as="admin"), [("blueprint_invalid", "/run_as")]),
        "popup severity": (_blueprint(alerts={"mode": "every_run", "severity": "high"}),
                           [("blueprint_invalid", "/alerts/severity")]),
        "NaN": (_blueprint(description=float("nan")), [("blueprint_invalid", "")]),
        "over 128 KB": (_blueprint(description="d" * (129 * 1024)), [("blueprint_invalid", "")]),
        "nested too deeply": (_blueprint(extra=nested), [("blueprint_invalid", "")]),
    }
    for label, (blueprint, expected) in cases.items():
        assert [(error["code"], error["path"]) for error in validate(blueprint)] == expected, label

    # The dry run reports the same errors, before reading anything.
    harness.calls.clear()
    result = harness.dry_run(_blueprint(name="n" * 121), EMAIL_HANDLES, check_quota=False)
    assert result == {"ok": False, "workflow": None, "errors": [{
        "code": "blueprint_invalid", "message": "Must be 120 characters or fewer.", "path": "/name",
    }]}
    assert harness.calls == []


def test_unsupported_field_rejects_every_free_form_destination_and_model_name(harness):
    blueprint = _blueprint(model="gpt-4o", endpoint="https://example.test")
    blueprint["tasks"] = [{
        "title": "Send it", "instructions": "Email the list.", "url": "https://example.test/hook",
        "document_ids": ["doc-checklist"],
        "runner": {"type": "agent", "agent_ref": "mail_agent", "model": "gpt-4o"},
    }]
    blueprint["trigger"] = {**EMAIL_DIGEST["trigger"], "unit": "hours"}
    blueprint["alerts"] = {"mode": "every_run", "recipients": ["someone@example.test"]}

    result = harness.dry_run(blueprint, EMAIL_HANDLES)

    assert result["ok"] is False
    assert _codes(result) == [
        ("unsupported_field", "/alerts/recipients"),
        ("unsupported_field", "/endpoint"),
        ("unsupported_field", "/model"),
        ("unsupported_field", "/tasks/0/document_ids"),
        ("unsupported_field", "/tasks/0/runner/model"),
        ("unsupported_field", "/tasks/0/url"),
        ("unsupported_field", "/trigger/unit"),
    ]
    assert harness.writes() == {}


def test_unsupported_field_rejects_fields_a_trigger_or_runner_does_not_use(harness):
    validate = harness.drafts.validate_workflow_blueprint
    cases = {
        "manual with a time": ({"type": "manual", "time_of_day": "08:00"}, "/trigger/time_of_day"),
        "daily with days": ({
            "type": "calendar", "frequency": "daily", "days_of_week": ["monday"],
            "time_of_day": "08:00", "timezone": "UTC",
        }, "/trigger/days_of_week"),
        "weekly with a day of the month": ({
            "type": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "day_of_month": 3,
            "time_of_day": "08:00", "timezone": "UTC",
        }, "/trigger/day_of_month"),
        "interval with a time zone": ({"type": "interval", "unit": "hours", "value": 2, "timezone": "UTC"},
                                      "/trigger/timezone"),
        "calendar File Sync schedule with a unit": ({
            "type": "file_sync", "source_ids": ["contracts"],
            "schedule": {"kind": "calendar", "frequency": "daily", "time_of_day": "08:00", "timezone": "UTC",
                         "unit": "hours"},
        }, "/trigger/schedule/unit"),
    }
    for label, (trigger, path) in cases.items():
        assert [(e["code"], e["path"]) for e in validate(_blueprint(trigger=trigger))] == [
            ("unsupported_field", path),
        ], label
    model_with_agent = _blueprint(tasks=[{
        "title": "T", "instructions": "I", "runner": {"type": "model", "agent_ref": "mail_agent"},
    }])
    assert [(e["code"], e["path"]) for e in validate(model_with_agent)] == [
        ("unsupported_field", "/tasks/0/runner/agent_ref"),
    ]


def test_too_many_tasks_applies_the_blueprint_and_admin_limits(harness):
    six = harness.dry_run(_blueprint(tasks=_tasks(6)))
    assert six["errors"] == [{
        "code": "too_many_tasks", "message": "A workflow created from chat can have up to 5 tasks.", "path": "/tasks",
    }]

    harness.settings["workflow_max_tasks"] = 3
    four = harness.dry_run(_blueprint(tasks=_tasks(4)))
    assert four["errors"] == [{
        "code": "too_many_tasks", "message": "This workflow can have up to 3 tasks.", "path": "/tasks",
    }]
    assert harness.dry_run(_blueprint(tasks=_tasks(3)))["ok"] is True


def test_trigger_invalid_points_at_the_field_to_fix(harness):
    validate = harness.drafts.validate_workflow_blueprint
    cases = {
        "unknown type": ({"type": "webhook"}, [("trigger_invalid", "/trigger/type")]),
        "missing trigger": (None, [("trigger_invalid", "/trigger")]),
        "weekly without days": ({
            "type": "calendar", "frequency": "weekly", "time_of_day": "08:00", "timezone": "UTC",
        }, [("trigger_invalid", "/trigger/days_of_week")]),
        "monthly without a day": ({
            "type": "calendar", "frequency": "monthly", "time_of_day": "08:00", "timezone": "UTC",
        }, [("trigger_invalid", "/trigger/day_of_month")]),
        "12-hour time": ({
            "type": "calendar", "frequency": "daily", "time_of_day": "8:00 AM", "timezone": "UTC",
        }, [("trigger_invalid", "/trigger/time_of_day")]),
        "day 32": ({
            "type": "calendar", "frequency": "monthly", "day_of_month": 32, "time_of_day": "08:00", "timezone": "UTC",
        }, [("trigger_invalid", "/trigger/day_of_month")]),
        "seconds": ({"type": "interval", "unit": "seconds", "value": 30}, [("trigger_invalid", "/trigger/unit")]),
        "25 hours": ({"type": "interval", "unit": "hours", "value": 25}, [("trigger_invalid", "/trigger/value")]),
        "File Sync without sources": ({
            "type": "file_sync", "schedule": {"kind": "interval", "unit": "hours", "value": 2},
        }, [("trigger_invalid", "/trigger/source_ids")]),
    }
    for label, (trigger, expected) in cases.items():
        blueprint = _blueprint(trigger=trigger) if trigger is not None else {
            k: v for k, v in EMAIL_DIGEST.items() if k != "trigger"
        }
        assert [(e["code"], e["path"]) for e in validate(blueprint)] == expected, label

    # A time zone name is checked against the server's IANA database, after the schema.
    calendar = harness.dry_run(_blueprint(trigger={**EMAIL_DIGEST["trigger"], "timezone": "Mars/Olympus"}), EMAIL_HANDLES)
    assert calendar["errors"] == [{
        "code": "trigger_invalid",
        "message": "Schedule time zone must be an IANA time zone name, such as America/New_York.",
        "path": "/trigger/timezone",
    }]
    review = copy.deepcopy(DOCUMENT_REVIEW)
    review["trigger"]["schedule"]["timezone"] = "Europe/Atlantis"
    assert _codes(harness.dry_run(review, REVIEW_HANDLES)) == [("trigger_invalid", "/trigger/schedule/timezone")]


def test_cadence_below_minimum_uses_the_larger_floor_and_passes_calendar_schedules(harness):
    every_30_minutes = _blueprint(trigger={"type": "interval", "unit": "minutes", "value": 30})
    result = harness.dry_run(every_30_minutes, EMAIL_HANDLES)
    assert result["errors"] == [{
        "code": "cadence_below_minimum",
        "message": (
            "Workflows created from chat cannot run this often. Choose an interval of at least 1 hour, "
            "or a daily, weekly or monthly schedule."
        ),
        "path": "/trigger",
    }]
    assert harness.dry_run(_blueprint(trigger={"type": "interval", "unit": "hours", "value": 1}), EMAIL_HANDLES)["ok"]

    # The general floor wins when an administrator sets it above the orchestration floor.
    harness.settings["workflow_min_schedule_interval_seconds"] = 7200
    hourly = harness.dry_run(_blueprint(trigger={"type": "interval", "unit": "hours", "value": 1}), EMAIL_HANDLES)
    assert _codes(hourly) == [("cadence_below_minimum", "/trigger")]
    assert "at least 2 hours" in hourly["errors"][0]["message"]
    harness.settings["workflow_min_schedule_interval_seconds"] = 300

    harness.settings["chat_orchestration_min_workflow_interval_seconds"] = 86400
    daily = harness.dry_run(_blueprint(trigger={
        "type": "calendar", "frequency": "daily", "time_of_day": "06:30", "timezone": "Asia/Tokyo",
    }), EMAIL_HANDLES)
    assert daily["ok"] is True, daily["errors"]
    assert _codes(harness.dry_run(_blueprint(trigger={"type": "interval", "unit": "hours", "value": 23}), EMAIL_HANDLES)) == [
        ("cadence_below_minimum", "/trigger"),
    ]

    review = copy.deepcopy(DOCUMENT_REVIEW)
    review["trigger"]["schedule"] = {"kind": "interval", "unit": "minutes", "value": 15}
    assert _codes(harness.dry_run(review, REVIEW_HANDLES)) == [("cadence_below_minimum", "/trigger/schedule")]


def test_a_manual_blueprint_has_no_schedule_to_check(harness):
    result = harness.dry_run(_blueprint(trigger={"type": "manual"}), EMAIL_HANDLES)
    assert result["ok"] is True, result["errors"]
    assert result["workflow"]["trigger_type"] == "manual"


def test_quota_exceeded_counts_only_live_orchestration_workflows(harness):
    harness.settings["chat_orchestration_max_workflows_per_user"] = 1
    container = harness.containers["personal_workflows"]
    container.items[(OWNER_ID, "manual-1")] = {"id": "manual-1", "user_id": OWNER_ID}
    container.items[(OWNER_ID, "deleting-1")] = {
        "id": "deleting-1", "user_id": OWNER_ID, "deleting": True, "origin": {"source": "orchestration"},
    }
    assert harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES)["ok"] is True

    container.items[(OWNER_ID, "chat-1")] = {"id": "chat-1", "user_id": OWNER_ID, "origin": {"source": "orchestration"}}
    result = harness.dry_run(_blueprint(name=""), EMAIL_HANDLES)
    # Checked before the schema, so the user is not asked to repair a blueprint that cannot be created.
    assert result["errors"] == [{
        "code": "quota_exceeded",
        "message": "You already have 1 workflow created from chat, the most allowed. Delete one before adding another.",
        "path": "",
    }]
    assert harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES, check_quota=False)["ok"] is True

    harness.settings["chat_orchestration_max_workflows_per_user"] = 2
    with harness.active():
        assert harness.drafts.check_orchestration_workflow_quota(OWNER_ID, harness.settings) is None
        container.items[(OWNER_ID, "chat-2")] = {
            "id": "chat-2", "user_id": OWNER_ID, "origin": {"source": "orchestration"},
        }
        error = harness.drafts.check_orchestration_workflow_quota(OWNER_ID, harness.settings)
    assert error["message"].startswith("You already have 2 workflows created from chat")


def test_agent_unavailable_applies_the_existing_agent_rules_at_every_use(harness):
    two_tasks = _blueprint(tasks=[
        {"title": "Read", "instructions": "Read my email.", "runner": {"type": "agent", "agent_ref": "mail_agent"}},
        {"title": "List", "instructions": "List the to-dos.", "runner": {"type": "agent", "agent_ref": "mail_agent"}},
    ])
    missing = {"agents": {"mail_agent": {"id": "agent-missing"}}}
    assert _codes(harness.dry_run(two_tasks, missing)) == [
        ("agent_unavailable", "/tasks/0/runner/agent_ref"),
        ("agent_unavailable", "/tasks/1/runner/agent_ref"),
    ]

    # A global agent is selectable only where global agents merge into the user's workspace.
    global_agent = {"agents": {"mail_agent": {"id": "agent-global", "is_global": True}}}
    assert _codes(harness.dry_run(EMAIL_DIGEST, global_agent)) == [("agent_unavailable", "/tasks/0/runner/agent_ref")]
    harness.settings.update({"per_user_semantic_kernel": True, "merge_global_semantic_kernel_with_workspace": True})
    merged = harness.dry_run(EMAIL_DIGEST, global_agent)
    assert merged["ok"] is True, merged["errors"]
    assert merged["workflow"]["tasks"][0]["runner"]["selected_agent"]["is_global"] is True

    harness.settings["allow_user_agents"] = False
    result = harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES)
    assert result["errors"] == [{
        "code": "agent_unavailable",
        "message": "This agent is not available to you. Choose another agent, or use the default model.",
        "path": "/tasks/0/runner/agent_ref",
    }]
    # Other checks still run, so one repair round can fix everything at once.
    both = copy.deepcopy(two_tasks)
    both["trigger"] = {"type": "interval", "unit": "minutes", "value": 5}
    assert [code for code, _ in _codes(harness.dry_run(both, EMAIL_HANDLES))] == [
        "agent_unavailable", "agent_unavailable", "cadence_below_minimum",
    ]


def test_reference_unknown_rejects_unmapped_and_malformed_handles(harness):
    blueprint = copy.deepcopy(DOCUMENT_REVIEW)
    blueprint["tasks"][1]["inputs"] = ["budget"]
    blueprint["tasks"][1]["runner"] = {"type": "agent", "agent_ref": "helper"}
    blueprint["trigger"]["source_ids"] = ["contracts", "archive"]
    result = harness.dry_run(blueprint, REVIEW_HANDLES)
    assert result["errors"] == [
        {"code": "reference_unknown", "message": "No document was provided for this handle.",
         "path": "/tasks/1/inputs/0"},
        {"code": "reference_unknown", "message": "No agent was provided for this handle.",
         "path": "/tasks/1/runner/agent_ref"},
        {"code": "reference_unknown", "message": "No File Sync source was provided for this handle.",
         "path": "/trigger/source_ids/1"},
    ]
    # Nothing is authorized until every handle is known.
    assert not harness.called("resolve_document_context")
    assert not harness.called("get_authorized_sync_source")

    malformed = copy.deepcopy(DOCUMENT_REVIEW)
    malformed["tasks"][0]["inputs"] = ["Q3 Report.pdf"]
    assert harness.dry_run(malformed, REVIEW_HANDLES)["errors"] == [{
        "code": "reference_unknown", "message": "This handle is not one provided with this request.",
        "path": "/tasks/0/inputs/0",
    }]
    with pytest.raises(ValueError):
        harness.call(
            "build_workflow_blueprint_payload", blueprint, REVIEW_HANDLES,
            workflow_id=harness.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID),
            user_id=OWNER_ID, settings=harness.settings,
        )


def test_reference_unauthorized_checks_each_document_as_the_requesting_user(harness):
    handles = copy.deepcopy(REVIEW_HANDLES)
    handles["documents"]["checklist"]["document_id"] = "doc-someone-else"
    result = harness.dry_run(DOCUMENT_REVIEW, handles)
    assert result["errors"] == [{
        "code": "reference_unauthorized", "message": "This document is not available to you.",
        "path": "/tasks/0/inputs/0",
    }]
    assert "doc-someone-else" not in json.dumps(result)
    [resolved] = harness.called("resolve_document_context")
    assert resolved[1]["user_id"] == OWNER_ID and resolved[1]["document_id"] == "doc-someone-else"


def test_file_sync_source_unavailable_requires_the_source_and_file_sync_for_its_scope(harness):
    handles = copy.deepcopy(REVIEW_HANDLES)
    handles["sources"]["contracts"]["source_id"] = "missing-share"
    assert harness.dry_run(DOCUMENT_REVIEW, handles)["errors"] == [{
        "code": "file_sync_source_unavailable", "message": "This File Sync source is not available to you.",
        "path": "/trigger/source_ids/0",
    }]

    harness.personal_file_sync_enabled = False
    reads_before = len(harness.called("get_authorized_sync_source"))
    assert _codes(harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES)) == [
        ("file_sync_source_unavailable", "/trigger/source_ids/0"),
    ]
    # With File Sync off for the source's scope, the source itself is never read.
    assert len(harness.called("get_authorized_sync_source")) == reads_before


def test_workflows_unavailable_applies_the_personal_workflow_gate(harness):
    harness.settings["allow_user_workflows"] = False
    assert harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES)["errors"] == [{
        "code": "workflows_unavailable", "message": "Personal workflows are not available for this account.",
        "path": "",
    }]
    assert harness.create(EMAIL_DIGEST, EMAIL_HANDLES)["created"] is False

    harness.settings.update({"allow_user_workflows": True, "require_member_of_workflow_user": True})
    assert _codes(harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES)) == [("workflows_unavailable", "")]
    assert harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES, user_info={"roles": ["WorkflowUser"]})["ok"] is True
    assert harness.writes() == {}


def test_errors_never_echo_input_and_are_capped_and_sorted(harness):
    blueprint = _blueprint(**{"<script>alert(1)</script>": "x", "run_as": "<img src=x onerror=alert(1)>"})
    blueprint["name"] = "<b>" * 50
    result = harness.dry_run(blueprint, EMAIL_HANDLES)
    encoded = json.dumps(result)
    assert "<" not in encoded and "script" not in encoded and "onerror" not in encoded
    assert _codes(result) == [
        ("unsupported_field", ""),
        ("blueprint_invalid", "/name"),
        ("blueprint_invalid", "/run_as"),
    ]
    assert result["errors"][2]["message"] == 'Must be one of: "self", "none".'
    assert all(len(error["message"]) <= 240 for error in result["errors"])

    many = _blueprint(tasks=[{"title": "T", "instructions": "I", "extra": 1} for _ in range(12)])
    paths = [error["path"] for error in harness.dry_run(many, EMAIL_HANDLES)["errors"]]
    # Ten errors at most, with array indexes in numeric order.
    assert paths == ["/tasks"] + [f"/tasks/{index}/extra" for index in range(9)]


def test_a_malformed_handle_map_or_origin_is_a_caller_bug(harness):
    bad_maps = [
        [],
        {"urls": {}},
        {"documents": {"Bad Handle": {"document_id": "d", "scope_type": "personal"}}},
        {"documents": {"doc": {"document_id": "d", "scope_type": "personal", "scope_id": "someone-else"}}},
        {"documents": {"doc": {"document_id": "", "scope_type": "personal"}}},
        {"documents": {"doc": {"document_id": "d", "scope_type": "tenant"}}},
        {"agents": {"agent": {"id": "a", "is_global": "yes"}}},
        {"agents": {"agent": {"id": "a", "endpoint": "https://example.test"}}},
        {"sources": {"src": {"scope_type": "group", "source_id": "s"}}},
    ]
    for handles in bad_maps:
        with pytest.raises(ValueError):
            harness.dry_run(EMAIL_DIGEST, handles)
    for origin in (None, {"source": "orchestration"}, {**ORIGIN, "source": "import"}):
        with pytest.raises(ValueError):
            harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES, origin=origin)
    with pytest.raises(ValueError):
        harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES, settings={})
    assert harness.writes() == {}

    with harness.active():
        normalized = harness.drafts.normalize_workflow_draft_handles({
            "documents": {"doc": {"document_id": " d-1 ", "scope_type": "personal"}},
        }, user_id=OWNER_ID)
    assert normalized == {
        "documents": {"doc": {"document_id": "d-1", "scope_type": "personal", "scope_id": OWNER_ID}},
        "agents": {}, "sources": {},
    }


TIMESTAMP_FIELDS = frozenset({"created_at", "modified_at", "updated_at"})


def _reversed_keys(value):
    if isinstance(value, dict):
        return {key: _reversed_keys(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reversed_keys(item) for item in value]
    return value


def _without(document, ignored):
    return {key: value for key, value in document.items() if key not in ignored and not key.startswith("_")}


def test_the_builder_is_deterministic(harness):
    workflow_id = harness.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID)

    def build(blueprint, handles):
        return harness.call(
            "build_workflow_blueprint_payload", blueprint, handles, workflow_id=workflow_id,
            user_id=OWNER_ID, settings=harness.settings,
        )

    for blueprint, handles in ((EMAIL_DIGEST, EMAIL_HANDLES), (DOCUMENT_REVIEW, REVIEW_HANDLES)):
        first = build(blueprint, handles)
        assert json.dumps(build(blueprint, handles)) == json.dumps(first)
        # Key order is not meaning, so it never changes the payload, byte for byte.
        assert json.dumps(build(_reversed_keys(blueprint), _reversed_keys(handles))) == json.dumps(first)

    first = harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES)["workflow"]
    second = harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES)["workflow"]
    revision = harness.modules["functions_workflow_definitions"].workflow_definition_revision
    assert revision(first) == revision(second)
    assert _without(first, TIMESTAMP_FIELDS) == _without(second, TIMESTAMP_FIELDS)

    other = harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES, origin={**ORIGIN, "proposal_id": "proposal-2"})["workflow"]
    assert other["id"] != first["id"]
    assert {task["id"] for task in other["tasks"]}.isdisjoint(task["id"] for task in first["tasks"])
    assert {rule["id"] for rule in other["alert_rules"]}.isdisjoint(rule["id"] for rule in first["alert_rules"])
    assert other["reference_inputs"][0]["id"] != first["reference_inputs"][0]["id"]

    derive = harness.drafts.orchestration_workflow_id
    assert derive("user-a", "p-1") == derive("user-a", "p-1") != derive("user-b", "p-1")
    with pytest.raises(ValueError):
        derive(OWNER_ID, " ")


def test_digest_alerts_reach_the_bell_and_never_pop_up(harness):
    completed = ("Run completed", "info", ["completed"])
    errors = ("Run had errors", "low", ["failed", "completed_with_task_errors"])

    def rules(alerts):
        blueprint = _blueprint(alerts=alerts) if alerts is not None else {
            key: value for key, value in EMAIL_DIGEST.items() if key != "alerts"
        }
        workflow = harness.dry_run(blueprint, EMAIL_HANDLES)["workflow"]
        # The every_run mode always opens a pop-up, so a digest uses rules delivered to the bell.
        assert (workflow["alert_mode"], workflow["alert_priority"]) == ("rules", "none")
        assert workflow["alert_evaluation"] == {"on_error": "skip"}
        assert {rule["delivery"] for rule in workflow["alert_rules"]} == {"notify_only"}
        assert {rule["scope"]["type"] for rule in workflow["alert_rules"]} == {"final"}
        return [(rule["name"], rule["severity"], rule["condition"]["statuses"]) for rule in workflow["alert_rules"]]

    assert rules(None) == [completed, errors]
    assert rules({}) == [completed, errors]
    assert rules({"mode": "every_run", "severity": "info"}) == [completed, errors]
    assert rules({"mode": "every_run", "severity": "low"}) == [("Run completed", "low", ["completed"]), errors]
    assert rules({"mode": "failures_only"}) == [errors]


def test_file_sync_defaults_wait_for_the_sync_and_continue_only_on_changes(harness):
    workflow = harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES)["workflow"]
    file_sync = workflow["file_sync"]
    assert {key: file_sync[key] for key in ("enabled", "wait_mode", "continue_mode", "use_changed_documents")} == {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
    }
    assert [(source["scope_type"], source["scope_id"], source["source_id"]) for source in file_sync["sources"]] == [
        ("personal", OWNER_ID, "my-share"),
    ]
    assert "never-store" not in json.dumps(workflow), "A source's credentials are never copied into a workflow."
    # The first task analyzes the documents each sync changed.
    assert [task["document_action"]["type"] for task in workflow["tasks"]] == ["analyze", "none"]

    harness.settings["document_action_capabilities"] = {"analyze": {"enabled": False}}
    workflow = harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES)["workflow"]
    assert [task["document_action"]["type"] for task in workflow["tasks"]] == ["none", "none"]
    assert workflow["file_sync"]["use_changed_documents"] is True


def test_the_model_runner_uses_the_default_model(harness):
    workflow = harness.dry_run(DOCUMENT_REVIEW, REVIEW_HANDLES)["workflow"]
    assert [task["runner"] for task in workflow["tasks"]] == [{"type": "inherit"}, {"type": "inherit"}]
    assert (workflow["runner_type"], workflow["model_endpoint_id"], workflow["model_id"]) == ("model", "", "")
    assert workflow["m365_run_as_user_id"] == ""


def test_the_dry_run_returns_the_document_the_create_stores(harness):
    dry = harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES)["workflow"]
    created = harness.create(EMAIL_DIGEST, EMAIL_HANDLES)["workflow"]
    stored = harness.load_personal(created["id"])
    ignored = TIMESTAMP_FIELDS | {"definition_revision"}
    assert _without(dry, ignored) == _without(stored, ignored)


def test_create_stores_one_paused_workflow_per_proposal_even_at_the_cap(harness):
    workflow_id = harness.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID)
    created = harness.create(EMAIL_DIGEST, EMAIL_HANDLES)

    assert created["ok"] is True and created["created"] is True, created["errors"]
    workflow = created["workflow"]
    assert workflow["id"] == workflow_id
    assert workflow["is_enabled"] is False and workflow["next_run_at"] is None
    assert workflow["origin"] == {**ORIGIN, "edited": False}
    assert workflow["definition_revision"], "The create returns an editor-ready workflow."
    assert not any(key.startswith("_") for key in workflow)
    assert harness.writes() == {"personal_workflows": [("create_item", workflow_id)]}
    assert not harness.called("get_user_settings") and not harness.called("get_settings")

    # Accepting the same proposal again finds the first workflow, even at the cap it now fills.
    harness.settings["chat_orchestration_max_workflows_per_user"] = 1
    again = harness.create(EMAIL_DIGEST, EMAIL_HANDLES)
    assert (again["ok"], again["created"], again["errors"]) == (True, False, [])
    assert again["workflow"] == workflow
    assert harness.writes() == {"personal_workflows": [("create_item", workflow_id)]}

    other = harness.create(EMAIL_DIGEST, EMAIL_HANDLES, origin={**ORIGIN, "proposal_id": "proposal-2"})
    assert (other["created"], _codes(other)) == (False, [("quota_exceeded", "")])


def test_create_and_start_schedules_the_first_calendar_run(harness):
    workflow = harness.create(EMAIL_DIGEST, EMAIL_HANDLES, enabled=True)["workflow"]
    assert workflow["is_enabled"] is True
    first_run = datetime.fromisoformat(workflow["next_run_at"]).astimezone(ZoneInfo("America/New_York"))
    assert (first_run.strftime("%A"), first_run.hour, first_run.minute) == ("Monday", 8, 0)


def test_create_never_adopts_or_revives_another_record_under_its_id(harness):
    workflow_id = harness.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID)
    container = harness.containers["personal_workflows"]
    cases = [
        ({"id": workflow_id, "user_id": OWNER_ID, "name": "Mine"}, "A different workflow already uses this id."),
        ({"id": workflow_id, "user_id": OWNER_ID, "origin": {**ORIGIN, "proposal_id": "proposal-9", "edited": False}},
         "A different workflow already uses this id."),
        ({"id": workflow_id, "user_id": OWNER_ID, "deleting": True, "origin": {**ORIGIN, "edited": False}},
         "This workflow is being deleted. Your draft was not saved."),
    ]
    for record, message in cases:
        container.items[(OWNER_ID, workflow_id)] = record
        result = harness.create(EMAIL_DIGEST, EMAIL_HANDLES)
        assert result == {
            "ok": False, "workflow": None, "created": False,
            "errors": [{"code": "workflow_conflict", "message": message, "path": ""}],
        }, record
        assert container.items[(OWNER_ID, workflow_id)] == record
    assert harness.writes() == {}


def test_a_create_rejected_by_a_draft_check_writes_nothing(harness):
    result = harness.create(_blueprint(trigger={"type": "interval", "unit": "minutes", "value": 10}), EMAIL_HANDLES)
    assert (result["created"], _codes(result)) == (False, [("cadence_below_minimum", "/trigger")])
    assert harness.writes() == {}


def test_a_misconfigured_limit_is_a_server_fault_not_a_draft_error(harness):
    limit_error = harness.modules["functions_workflow_limits"].WorkflowLoopLimitError
    payload = _v2("Hourly", trigger_type="interval", schedule={"unit": "hours", "value": 1},
                  tasks=[_task("t1", "Check", "Check the queue.")])
    for setting, value in (
        ("chat_orchestration_max_workflows_per_user", 0),
        ("chat_orchestration_min_workflow_interval_seconds", 30),
    ):
        harness.settings = {**harness.settings, setting: value}
        with pytest.raises(limit_error):
            harness.dry_run(EMAIL_DIGEST, EMAIL_HANDLES)
        with pytest.raises(limit_error):
            harness.create(EMAIL_DIGEST, EMAIL_HANDLES)
        with pytest.raises(limit_error):
            harness.call(
                "create_personal_workflow_from_payload", OWNER_ID, payload, origin=ORIGIN,
                settings=harness.settings, user_info=USER_INFO,
            )
        harness.settings.pop(setting)
    assert harness.writes() == {}


def test_a_personal_payload_dry_run_builds_what_a_save_stores_and_catches_stale_drafts(harness):
    payload = _v2(
        "Weekly planning", trigger_type="interval", schedule={
            "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"],
            "time_of_day": "08:00", "timezone": "America/New_York",
        },
        tasks=[_task("gather", "Gather", "List this week's meetings.")],
    )
    dry = harness.call("dry_run_personal_workflow", OWNER_ID, payload, settings=harness.settings)
    assert dry["ok"] is True, dry["errors"]
    assert harness.writes() == {}

    saved = harness.save_personal("create", payload)
    assert saved["definition_revision"] == harness.modules[
        "functions_workflow_definitions"
    ].workflow_definition_revision(dry["workflow"])
    # The save assigns its own new id, and the Microsoft 365 fingerprint covers the id.
    id_bound = TIMESTAMP_FIELDS | {"id", "m365_revision"}
    assert _without(dry["workflow"], id_bound) == _without(saved, id_bound | {"definition_revision"})

    writes = harness.writes()
    stale = {**saved, "description": "Plan the whole week.", "definition_revision": "0" * 64}
    result = harness.call("dry_run_personal_workflow", OWNER_ID, stale, actor_user_id=OWNER_ID, settings=harness.settings)
    assert result["errors"] == [{
        "code": "workflow_definition_conflict",
        "message": "This workflow changed since it was opened. Reload it before saving.",
        "path": "",
    }]
    current = {**saved, "description": "Plan the whole week."}
    result = harness.call("dry_run_personal_workflow", OWNER_ID, current, actor_user_id=OWNER_ID, settings=harness.settings)
    assert result["ok"] is True and result["workflow"]["description"] == "Plan the whole week."
    assert harness.load_personal(saved["id"])["description"] == ""
    assert harness.writes() == writes

    invalid = harness.call("dry_run_personal_workflow", OWNER_ID, {**payload, "name": ""}, settings=harness.settings)
    assert [error["code"] for error in invalid["errors"]] in (["invalid_workflow"], ["invalid_workflow_settings"])


def test_a_group_payload_dry_run_writes_nothing(harness):
    payload = _v2("Team digest", tasks=[_task("sum", "Summarize", "Summarize the week.")])
    with harness.guarded():
        result = harness.call(
            "dry_run_group_workflow", GROUP_ID, payload, OWNER_ID, user_info=USER_INFO, settings=harness.settings,
        )
    assert result["ok"] is True, result["errors"]
    assert result["workflow"]["group_id"] == GROUP_ID and result["workflow"]["conversation_id"] == ""
    assert harness.writes() == {}

    file_sync = _v2(
        "Team sync", trigger_type="file_sync", schedule={"unit": "hours", "value": 2},
        file_sync={"enabled": True, "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "gone"}]},
        tasks=[_task("sum", "Summarize", "Summarize the changes.")],
    )
    result = harness.call(
        "dry_run_group_workflow", GROUP_ID, file_sync, OWNER_ID, user_info=USER_INFO, settings=harness.settings,
    )
    assert result["ok"] is False and len(result["errors"]) == 1
    assert harness.writes() == {}


def test_create_from_an_edited_payload_uses_the_same_id_origin_and_limits(harness):
    workflow_id = harness.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID)
    payload = harness.call(
        "build_workflow_blueprint_payload", EMAIL_DIGEST, EMAIL_HANDLES, workflow_id=workflow_id,
        user_id=OWNER_ID, settings=harness.settings,
    )
    payload["name"] = "My weekly digest"

    def create(data):
        return harness.call(
            "create_personal_workflow_from_payload", OWNER_ID, data, origin=ORIGIN,
            settings=harness.settings, user_info=USER_INFO,
        )

    assert create({**payload, "id": "another-workflow"})["errors"] == [{
        "code": "workflow_conflict", "message": "This draft names a different workflow.", "path": "/id",
    }]
    too_often = create({**payload, "trigger_type": "interval", "schedule": {"unit": "minutes", "value": 30}})
    assert _codes(too_often) == [("cadence_below_minimum", "")]
    assert harness.writes() == {}

    created = create({**payload, "id": workflow_id})
    assert (created["ok"], created["created"]) == (True, True), created["errors"]
    workflow = created["workflow"]
    assert (workflow["id"], workflow["name"], workflow["is_enabled"]) == (workflow_id, "My weekly digest", False)
    assert workflow["origin"] == {**ORIGIN, "edited": False}

    again = create(payload)
    assert (again["created"], again["workflow"]["id"]) == (False, workflow_id)
    # Either accept path creates the proposal's workflow once.
    assert harness.create(EMAIL_DIGEST, EMAIL_HANDLES)["created"] is False
    assert harness.writes() == {"personal_workflows": [("create_item", workflow_id)]}


def test_create_from_a_payload_never_authorizes_url_access(harness):
    workflow_id = harness.drafts.orchestration_workflow_id(OWNER_ID, PROPOSAL_ID)
    payload = harness.call(
        "build_workflow_blueprint_payload", EMAIL_DIGEST, EMAIL_HANDLES, workflow_id=workflow_id,
        user_id=OWNER_ID, settings=harness.settings,
    )
    # The runner trusts a stored authorization in place of the UrlAccessUser role.
    forged = {
        "url_access_authorized": True, "url_access_authorized_by": OWNER_ID,
        "url_access_authorized_at": "2026-01-01T00:00:00+00:00",
    }

    def create(data):
        return harness.call(
            "create_personal_workflow_from_payload", OWNER_ID, data, origin=ORIGIN,
            settings=harness.settings, user_info=USER_INFO,
        )

    for requested in (True, "on"):
        refused = create({**payload, **forged, "url_access_enabled": requested})
        assert refused["errors"] == [{
            "code": "unsupported_field", "path": "/url_access_enabled",
            "message": "URL Access is not available for workflows created from chat. Turn it off.",
        }]
    assert harness.writes() == {}

    created = create({**payload, **forged, "url_access_enabled": False})
    assert (created["ok"], created["created"]) == (True, True), created["errors"]
    stored = harness.containers["personal_workflows"].items[(OWNER_ID, workflow_id)]
    assert [stored[field] for field in (
        "url_access_enabled", "url_access_authorized", "url_access_authorized_by", "url_access_authorized_at",
    )] == [False, False, "", ""]
    # Accepting again returns the stored workflow, whatever the new payload asks for.
    assert create({**payload, **forged, "url_access_enabled": True})["created"] is False
    assert harness.writes() == {"personal_workflows": [("create_item", workflow_id)]}


def test_workflows_without_an_orchestration_origin_are_unaffected(harness):
    harness.settings["chat_orchestration_max_workflows_per_user"] = 1
    harness.containers["personal_workflows"].items[(OWNER_ID, "chat-1")] = {
        "id": "chat-1", "user_id": OWNER_ID, "origin": {"source": "orchestration"},
    }
    every_ten_minutes = _v2(
        "Queue check", trigger_type="interval", schedule={"unit": "minutes", "value": 10},
        tasks=[_task("check", "Check", "Check the queue.")],
    )
    saved = harness.save_personal("create", every_ten_minutes)
    assert saved["schedule"] == {"unit": "minutes", "value": 10} and "origin" not in saved
    dry = harness.call("dry_run_personal_workflow", OWNER_ID, every_ten_minutes, settings=harness.settings)
    assert dry["ok"] is True, dry["errors"]
