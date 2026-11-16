# test_workflow_assist_cosmos_response_contract.py
"""
Functional regressions for the Ask AI workflow base reader's Cosmos response contract.
Version: 0.261.344
Implemented in: 0.261.330

The real installed SDK reads through the shared offline HTTP transport fixture.
These tests cover editor projection, metadata removal, partition isolation and
invalid identifiers without contacting Azure or replacing the storage owner.
"""

from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from azure.cosmos._cosmos_responses import CosmosDict
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Standalone execution establishes repository paths before importing real modules.
import functions_workflow_assist_runtime as runtime  # noqa: E402
from functions_workflow_alert_safety import WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE  # noqa: E402
from functions_workflow_definitions import workflow_definition_revision  # noqa: E402
from test_m365_cosmos_sdk_contract import cosmos_factory  # noqa: E402, F401


@pytest.mark.parametrize("definition_version", [1, 2, 3])
def test_workflow_base_projects_real_sdk_point_response(cosmos_factory, definition_version):
    http, container = cosmos_factory("user_id")
    diagnostic = "Alert condition could not be evaluated: SENTINEL provider detail"
    stored = http.seed({
        "id": "workflow", "user_id": "owner", "name": "Document review",
        "definition_version": definition_version, "definition_revision": "stale",
        "tasks": [{"id": "review", "name": "Review", "prompt": "Review documents."}],
        "schedule": {"kind": "calendar", "frequency": "weekdays", "time_of_day": "07:00"},
        "alert_decision": {
            "matched_rules": [{"condition_type": "model_evaluation", "reason": diagnostic}],
            "message": diagnostic,
        },
    })
    point = container.read_item(item="workflow", partition_key="owner")
    before = deepcopy(http.records)

    loaded = runtime.read_workflow_base(container, "owner", "workflow")

    assert isinstance(point, CosmosDict)
    assert type(point) is not dict
    assert type(loaded) is dict
    assert loaded["id"] == "workflow"
    assert loaded["user_id"] == "owner"
    assert loaded["definition_version"] == definition_version
    assert loaded["tasks"] == stored["tasks"]
    assert type(loaded["tasks"][0]) is dict
    assert loaded["schedule"] == stored["schedule"]
    assert not any(key.startswith("_") for key in loaded)
    expected_revision = workflow_definition_revision(stored)
    assert loaded["definition_revision"] == expected_revision
    assert loaded["definition_revision"] != "stale"
    assert loaded["alert_decision"]["message"] == WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
    assert loaded["alert_decision"]["matched_rules"][0]["reason"] == WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
    assert http.records == before
    assert point["alert_decision"]["message"] == diagnostic
    assert all(method == "GET" for method, _path, _headers in http.calls)
    item_reads = [headers for method, path, headers in http.calls if path.endswith("/docs/workflow")]
    assert len(item_reads) == 2
    assert all(headers["x-ms-documentdb-partitionkey"] == '["owner"]' for headers in item_reads)


@pytest.mark.parametrize("user_id, workflow_id", [("someone-else", "workflow"), ("owner", "missing")])
def test_workflow_base_missing_or_foreign_item_uses_real_sdk_404(cosmos_factory, user_id, workflow_id):
    http, container = cosmos_factory("user_id")
    http.seed({"id": "workflow", "user_id": "owner", "name": "Private workflow"})
    before = deepcopy(http.records)

    loaded = runtime.read_workflow_base(container, user_id, workflow_id)

    assert loaded is None
    assert http.records == before
    item_reads = [(path, headers) for method, path, headers in http.calls if "/docs/" in path]
    assert len(item_reads) == 1
    path, headers = item_reads[0]
    assert path.endswith(f"/docs/{workflow_id}")
    assert headers["x-ms-documentdb-partitionkey"] == f'["{user_id}"]'


@pytest.mark.parametrize("character", ["/", "\\", "?", "#"])
def test_workflow_base_invalid_id_never_calls_sdk(cosmos_factory, character):
    http, container = cosmos_factory("user_id")
    before = list(http.calls)

    loaded = runtime.read_workflow_base(container, "owner", f"workflow{character}other")

    assert loaded is None
    assert http.calls == before


def test_group_workflow_base_uses_route_partition_and_rejects_foreign_group(cosmos_factory):
    http, container = cosmos_factory("group_id")
    http.seed({
        "id": "workflow", "group_id": "authorized-group", "user_id": "creator",
        "name": "Group review", "definition_version": 2,
        "chat_execution": {"version": 1, "mode": "selected",
                           "required_capabilities": ["web_search"], "visual_requirements": []},
        "results_delivery": {"version": 1, "mode": "conversation", "conversation_type": "group",
                             "recipient_ids": [], "all_group_members": False},
        "tasks": [{"id": "review", "name": "Review", "prompt": "Review documents."}],
    })
    before = deepcopy(http.records)
    loaded = runtime.read_workflow_base(container, "manager", "workflow", group_id="authorized-group")
    missing = runtime.read_workflow_base(container, "manager", "workflow", group_id="another-group")
    assert loaded["group_id"] == "authorized-group"
    assert loaded["user_id"] == "creator"
    assert loaded["chat_execution"]["required_capabilities"] == ["web_search"]
    assert loaded["results_delivery"]["conversation_type"] == "group"
    assert type(loaded) is dict
    assert missing is None
    assert http.records == before
    reads = [headers for method, path, headers in http.calls if path.endswith("/docs/workflow")]
    assert [headers["x-ms-documentdb-partitionkey"] for headers in reads] == [
        '["authorized-group"]', '["another-group"]',
    ]


def test_group_assist_services_bind_all_adapters_and_recheck_management(cosmos_factory, monkeypatch):
    http, container = cosmos_factory("group_id")
    http.seed({"id": "workflow", "group_id": "team", "user_id": "creator", "name": "Team",
               "definition_version": 2, "tasks": [{"id": "review", "prompt": "Review."}]})
    calls = []
    permitted = [True]
    def role(actor, group, *, allowed_roles):
        calls.append(("role", actor, group, allowed_roles))
        if not permitted[0]:
            raise PermissionError("revoked")
        return "Admin"
    def dry_run(group, payload, actor, **kwargs):
        calls.append(("dry_run", group, actor, kwargs["user_info"]))
        return {"ok": True}
    def excerpt(workflow, reference, **kwargs):
        calls.append(("excerpt", workflow, kwargs))
        return {"text": "Authorized group document"}
    def options(actor, settings, **kwargs):
        calls.append(("options", actor, kwargs))
        return {"results_delivery": {"recipient_choices": []}}
    def manifest(workflow):
        calls.append(("manifest", workflow))
        return [], workflow
    attributes = {
        "config": {"TENANT_ID": "tenant", "cosmos_personal_workflows_container": None,
                   "cosmos_group_workflows_container": container, "cosmos_settings_container": None},
        "functions_group": {"assert_group_role": role},
        "functions_settings": {"get_group_workflow_management_roles": lambda _settings: ("Owner", "Admin")},
        "functions_m365_connections": {"get_m365_connection_service": SimpleNamespace},
        "functions_m365_runtime": {"_manifest_sources": lambda _action: [], "workflow_m365_manifests": manifest},
        "functions_orchestration_context": {
            "ScopeReferenceError": ValueError, "resolve_scope_references": lambda references, *_args, **_kwargs: references,
        },
        "functions_workflow_bindings": {"load_workflow_reference": excerpt},
        "functions_workflow_drafts": {"dry_run_personal_workflow": None, "dry_run_group_workflow": dry_run},
        "functions_workflow_editor": {"get_workflow_editor_options": options},
    }
    for name, values in attributes.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    services = runtime.build_workflow_assist_services(
        {}, client_factory=lambda: None, group_id="team", user_info={"user_id": "manager"},
    )
    loaded = services.read_base("manager", "workflow")
    choices = services.load_options("manager")
    text = services.load_excerpt("manager", ("group", "team", "document"))
    validation = services.dry_run("manager", {"group_id": "team"})
    email = services.agent_email_capable("manager", {"id": "agent"})
    assert loaded["user_id"] == "creator"
    assert choices == {"results_delivery": {"recipient_choices": []}}
    assert text == "Authorized group document"
    assert validation["ok"] is True
    assert email is False
    assert ("dry_run", "team", "manager", {"user_id": "manager"}) in calls
    assert ("options", "manager", {"group_id": "team"}) in calls
    manifest_workflow = next(call[1] for call in calls if call[0] == "manifest")
    assert manifest_workflow["group_id"] == "team"
    with pytest.raises(runtime.WorkflowAssistError) as caught:
        services.load_excerpt("manager", ("personal", "manager", "private-document"))
    assert caught.value.code == "reference_unavailable"
    permitted[0] = False
    for adapter in (lambda: services.read_base("manager", "workflow"),
                    lambda: services.load_options("manager"),
                    lambda: services.dry_run("manager", {"group_id": "team"})):
        with pytest.raises(PermissionError):
            adapter()
    assert all(method == "GET" for method, _path, _headers in http.calls)


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve())]))
