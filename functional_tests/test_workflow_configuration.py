# test_workflow_configuration.py
"""
Functional tests for workflow execution selection and scoped results configuration.
Version: 0.261.343
Implemented in: 0.261.343

Real configuration, definition, compiler, editor mirror and storage modules are
exercised. Cosmos persistence uses the installed SDK with offline HTTP responses.
"""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from azure.cosmos._cosmos_responses import CosmosDict
import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Standalone execution establishes repository paths before real application imports.
import functions_workflow_assist_editor as editor  # noqa: E402
from functions_m365_workflow_binding import workflow_execution_fingerprint  # noqa: E402
from functions_orchestration_registry import all_capability_ids, VISUAL_KINDS  # noqa: E402
from functions_workflow_configuration import (  # noqa: E402
    WORKFLOW_CAPABILITY_IDS, WORKFLOW_VISUAL_REQUIREMENTS, WorkflowConfigurationError,
    new_workflow_configuration, normalize_chat_execution, normalize_results_delivery,
    resolve_workflow_chat_execution, workflow_configuration_for_save,
)
from functions_workflow_definitions import (  # noqa: E402
    WorkflowDefinitionError, normalize_workflow_definition,
    workflow_definition_revision,
)
from functions_workflow_runtime import _snapshot  # noqa: E402
from test_m365_cosmos_sdk_contract import cosmos_factory  # noqa: E402, F401
from test_workflow_draft_save_parity import (  # noqa: E402
    GROUP_ID, OWNER_ID, SaveParityHarness, _task, _v2,
)
from test_support.orchestration_revisions import AtomicMemoryContainer  # noqa: E402


RECIPIENT = "abcdef12-3456-7890-abcd-ef1234567890"
AUTOMATIC = {"version": 1, "mode": "orchestration", "required_capabilities": [], "visual_requirements": []}
SELECTED = {
    "version": 1, "mode": "selected", "required_capabilities": ["web_search"],
    "visual_requirements": ["chart"],
}
OFF = {"version": 1, "mode": "off", "required_capabilities": [], "visual_requirements": []}


def delivery(scope="personal", mode="conversation", **changes):
    return {
        "version": 1, "mode": mode, "conversation_type": "group" if scope == "group" else "personal",
        "recipient_ids": [], "all_group_members": False, **changes,
    }


def payload(**changes):
    return _v2(
        "Research digest",
        tasks=[_task("research", "Research", "Find current information."), _task("write", "Write", "Summarize it.")],
        **changes,
    )


@pytest.mark.parametrize("optimized", [False, True])
def test_configuration_cold_import_does_not_bootstrap_or_use_network(optimized):
    probe = f"""
import socket, sys
sys.path.insert(0, {str(APP)!r})
def forbidden(*args, **kwargs):
    raise RuntimeError("Network is forbidden")
socket.socket.connect = forbidden
socket.getaddrinfo = forbidden
import functions_workflow_configuration as configuration
configuration.normalize_chat_execution({AUTOMATIC!r})
if any(name in sys.modules for name in ("config", "functions_settings", "functions_appinsights")):
    raise RuntimeError("Configuration imported application bootstrap")
"""
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", probe],
        capture_output=True, text=True, cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_contract_vocabulary_matches_real_registry():
    registered = all_capability_ids()
    assert set(WORKFLOW_CAPABILITY_IDS) == {identity for identity in registered if not identity.startswith("workflow_")}
    assert WORKFLOW_VISUAL_REQUIREMENTS == VISUAL_KINDS


@pytest.mark.parametrize("capability", ["workflow_propose", "workflow_run", "workflow_results", "workflow_handoff"])
def test_ordinary_execution_contract_refuses_workflow_control_tools(capability):
    with pytest.raises(WorkflowConfigurationError):
        normalize_chat_execution({**SELECTED, "required_capabilities": [capability]})


def test_task_override_replaces_default_and_omission_is_legacy():
    workflow = {"chat_execution": SELECTED, "chat_capabilities_enabled": True}
    inherited = resolve_workflow_chat_execution(workflow, {})
    replaced = resolve_workflow_chat_execution(workflow, {"chat_execution": OFF})
    legacy = resolve_workflow_chat_execution({"chat_capabilities_enabled": True}, {})
    assert inherited == SELECTED
    assert replaced == OFF
    assert legacy is None
    inherited["required_capabilities"].clear()
    assert workflow["chat_execution"] == SELECTED


@pytest.mark.parametrize("value", [
    None, [], {"version": True, "mode": "off"}, {"version": 2, "mode": "off"},
    {"version": 1, "mode": "selected"}, {**SELECTED, "required_capabilities": ["not_a_tool"]},
    {**SELECTED, "required_capabilities": None}, {**SELECTED, "visual_requirements": ["mermaid"]},
    {**AUTOMATIC, "required_capabilities": ["web_search"]}, {**OFF, "visual_requirements": ["chart"]},
    {**SELECTED, "user_id": "someone"}, {**SELECTED, "required_capabilities": "web_search"},
])
def test_invalid_execution_contract_fails_closed(value):
    with pytest.raises(WorkflowConfigurationError):
        normalize_chat_execution(value)


def test_selections_are_positive_deduplicated_requirements():
    normalized = normalize_chat_execution({
        **SELECTED, "required_capabilities": ["web_search", "web_search"], "visual_requirements": ["diagram", "diagram"],
    })
    assert normalized["required_capabilities"] == ["web_search"]
    assert normalized["visual_requirements"] == ["diagram"]


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("available", [False, True])
def test_new_defaults_and_legacy_omission_stay_distinct(scope, available):
    settings = {"enable_chat_orchestration": available}
    new = workflow_configuration_for_save({}, settings=settings, workflow_scope=scope)
    legacy = workflow_configuration_for_save({}, {"chat_capabilities_enabled": False}, settings=settings, workflow_scope=scope)
    specialized = workflow_configuration_for_save({}, settings=settings, workflow_scope=scope, new_defaults=False)
    assert new["results_delivery"] == delivery(scope)
    assert ("chat_execution" in new) is available
    assert legacy == {}
    assert specialized == {}
    defaults = new_workflow_configuration(settings=settings, workflow_scope=scope)
    assert defaults["chat_capabilities_enabled"] is True


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_shared_delivery_uses_canonical_recipients(scope):
    value = delivery(scope, conversation_type="group_shared" if scope == "group" else "shared",
                     recipient_ids=[RECIPIENT.upper(), RECIPIENT])
    normalized = normalize_results_delivery(value, workflow_scope=scope)
    assert normalized["recipient_ids"] == [RECIPIENT]
    if scope == "group":
        everyone = normalize_results_delivery(
            delivery(scope, conversation_type="group_shared", all_group_members=True), workflow_scope=scope,
        )
        assert everyone["all_group_members"] is True
        assert "group_id" not in everyone


@pytest.mark.parametrize("scope,changes", [
    ("personal", {"conversation_type": "group"}),
    ("group", {"conversation_type": "personal"}),
    ("group", {"group_id": "other-group"}),
    ("personal", {"recipient_ids": [RECIPIENT]}),
    ("personal", {"conversation_type": "shared"}),
    ("personal", {"conversation_type": "shared", "recipient_ids": ["someone@example.com"]}),
    ("personal", {"all_group_members": True}),
    ("group", {"conversation_type": "group_shared", "all_group_members": True, "recipient_ids": [RECIPIENT]}),
    ("group", {"all_group_members": "true"}),
    ("personal", {"mode": "history", "conversation_type": "shared", "recipient_ids": [RECIPIENT]}),
    ("group", {"mode": "task", "conversation_type": "group_shared", "all_group_members": True}),
    ("personal", {"recipient_ids": None}),
])
def test_invalid_or_cross_scope_delivery_fails_closed(scope, changes):
    with pytest.raises(WorkflowConfigurationError):
        normalize_results_delivery(delivery(scope, **changes), workflow_scope=scope)


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_real_backend_save_round_trip_with_sdk_point_and_write_responses(cosmos_factory, scope):
    harness = SaveParityHarness()
    harness.settings["enable_chat_orchestration"] = True
    http, container = cosmos_factory("group_id" if scope == "group" else "user_id")
    if scope == "group":
        harness.group.cosmos_group_workflows_container = container
        save = lambda value: harness.group.save_group_workflow(GROUP_ID, value, OWNER_ID)
        load = lambda identifier: harness.group.get_group_workflow(GROUP_ID, identifier)
        partition = GROUP_ID
    else:
        harness.personal.cosmos_personal_workflows_container = container
        save = lambda value: harness.personal.save_personal_workflow(OWNER_ID, value)
        load = lambda identifier: harness.personal.get_personal_workflow(OWNER_ID, identifier)
        partition = OWNER_ID
    draft = payload()
    draft["tasks"][1]["chat_execution"] = deepcopy(OFF)
    created = save(draft)
    point = container.read_item(item=created["id"], partition_key=partition)
    assert isinstance(point, CosmosDict)
    assert created["chat_execution"] == AUTOMATIC
    assert created["results_delivery"] == delivery(scope)
    assert created["tasks"][1]["chat_execution"] == OFF
    assert "chat_execution" not in created["tasks"][0]
    updated = save({**created, "chat_execution": deepcopy(SELECTED)})
    loaded = load(updated["id"])
    assert loaded["chat_execution"] == SELECTED
    assert loaded["tasks"][1]["chat_execution"] == OFF
    assert loaded["results_delivery"] == delivery(scope)
    assert loaded["definition_revision"] != created["definition_revision"]
    omitted = {key: value for key, value in loaded.items() if key not in ("chat_execution", "results_delivery")}
    preserved = save(omitted)
    assert preserved["chat_execution"] == SELECTED
    assert preserved["results_delivery"] == delivery(scope)
    assert any(method == "PUT" for method, _path, _headers in http.calls)
    conflict = harness.modules["functions_workflow_definitions"].WorkflowDefinitionConflict
    with pytest.raises(conflict):
        save({**created, "name": "Stale"})
    with pytest.raises(conflict):
        save({**loaded, "definition_version": 1})


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("legacy_flag", [None, False, True])
def test_existing_legacy_backend_records_do_not_acquire_new_behavior(cosmos_factory, scope, legacy_flag):
    harness = SaveParityHarness()
    harness.settings["enable_chat_orchestration"] = True
    http, container = cosmos_factory("group_id" if scope == "group" else "user_id")
    legacy = {
        **payload(), "id": "legacy-workflow", "user_id": OWNER_ID, "chat_capabilities_enabled": legacy_flag,
        **({"group_id": GROUP_ID} if scope == "group" else {}),
    }
    if legacy_flag is None:
        legacy.pop("chat_capabilities_enabled")
    http.seed(legacy)
    if scope == "group":
        harness.group.cosmos_group_workflows_container = container
        loaded = harness.group.get_group_workflow(GROUP_ID, legacy["id"])
        saved = harness.group.save_group_workflow(GROUP_ID, loaded, OWNER_ID)
    else:
        harness.personal.cosmos_personal_workflows_container = container
        loaded = harness.personal.get_personal_workflow(OWNER_ID, legacy["id"])
        saved = harness.personal.save_personal_workflow(OWNER_ID, loaded)
    assert saved["chat_capabilities_enabled"] is (legacy_flag is True)
    assert "chat_execution" not in saved
    assert "results_delivery" not in saved


def test_configuration_and_task_overrides_survive_snapshot_and_invalidate_revisions():
    workflow = {
        **payload(), "id": "workflow", "user_id": OWNER_ID, "chat_execution": deepcopy(SELECTED),
        "results_delivery": delivery(), "deep_research_authorized": True,
        "deep_research_authorized_by": OWNER_ID, "deep_research_authorized_at": "2026-10-16T19:00:00Z",
    }
    workflow["tasks"][1]["chat_execution"] = deepcopy(OFF)
    frozen = _snapshot(workflow)
    assert frozen["chat_execution"] == SELECTED
    assert frozen["results_delivery"] == delivery()
    assert frozen["tasks"][1]["chat_execution"] == OFF
    assert frozen["deep_research_authorized_by"] == OWNER_ID
    revision = workflow_definition_revision(workflow)
    fingerprint = workflow_execution_fingerprint(workflow)
    workflow["chat_execution"] = deepcopy(AUTOMATIC)
    assert workflow_definition_revision(workflow) != revision
    assert workflow_execution_fingerprint(workflow) != fingerprint
    assert frozen["chat_execution"] == SELECTED
    revision = workflow_definition_revision(workflow)
    fingerprint = workflow_execution_fingerprint(workflow)
    workflow["results_delivery"] = delivery(mode="history")
    assert workflow_definition_revision(workflow) != revision
    assert workflow_execution_fingerprint(workflow) != fingerprint


def test_task_override_validation_runs_through_real_definition_boundary():
    raw = payload(chat_execution=deepcopy(AUTOMATIC), results_delivery=delivery())
    raw["tasks"][0]["chat_execution"] = deepcopy(SELECTED)
    normalized = normalize_workflow_definition(raw, None, raw["tasks"], user_id=OWNER_ID)
    assert normalized["chat_execution"] == AUTOMATIC
    assert normalized["results_delivery"] == delivery()
    assert normalized["tasks"][0]["chat_execution"] == SELECTED
    raw["tasks"][0]["chat_execution"] = None
    with pytest.raises(WorkflowDefinitionError):
        normalize_workflow_definition(raw, None, raw["tasks"], user_id=OWNER_ID)


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_server_owned_chat_origin_producers_keep_explicit_legacy_behavior(scope):
    harness = SaveParityHarness()
    harness.settings["enable_chat_orchestration"] = True
    origin = {
        "source": "orchestration", "conversation_id": "conv-chat", "orchestration_run_id": "chat-run",
        "proposal_id": "proposal", "created_at": "2026-10-16T19:00:00Z",
    }
    args = {"workflow_id": "12345678-1234-1234-1234-123456789012", "origin": origin}
    if scope == "group":
        built, existing = harness.group.build_group_workflow_document(GROUP_ID, payload(), OWNER_ID, **args)
    else:
        built, existing = harness.personal.build_personal_workflow_document(OWNER_ID, payload(), **args)
    assert existing is None
    assert built["chat_capabilities_enabled"] is False
    assert "chat_execution" not in built
    assert "results_delivery" not in built


def test_structured_task_catalogue_preserves_replacing_overrides():
    from functions_workflow_flow import compile_workflow_flow

    raw = {
        **payload(chat_execution=deepcopy(AUTOMATIC), results_delivery=delivery()),
        "definition_version": 3,
        "flow": {
            "id": "root", "nodes": [
                {"id": "research-node", "kind": "task", "task_id": "research"},
                {"id": "write-node", "kind": "task", "task_id": "write"},
            ], "outputs": [],
        },
    }
    raw["tasks"][0]["chat_execution"] = deepcopy(SELECTED)
    normalized = normalize_workflow_definition(raw, None, raw["tasks"], user_id=OWNER_ID)
    compiled = compile_workflow_flow({**raw, **normalized, "user_id": OWNER_ID})
    assert compiled["tasks"][0]["chat_execution"] == SELECTED
    assert "chat_execution" not in compiled["tasks"][1]


@pytest.mark.parametrize("scope", [{"type": "personal"}, {"type": "group", "groupId": GROUP_ID}])
def test_python_editor_default_and_save_projection_preserve_configuration(scope):
    options = {"chat_execution": {"default": AUTOMATIC}}
    draft = editor.new_workflow_definition(scope, options)
    draft["name"] = "Digest"
    draft["tasks"][0]["instructions"] = "Summarize current findings."
    draft["tasks"][0]["chat_execution"] = deepcopy(SELECTED)
    saved = editor.workflow_for_save(draft, None, scope)
    assert saved["chat_execution"] == AUTOMATIC
    assert saved["results_delivery"] == delivery(scope["type"])
    assert saved["tasks"][0]["chat_execution"] == SELECTED
    draft["tasks"][0].pop("chat_execution")
    inherited = editor.workflow_for_save(draft, None, scope)
    assert "chat_execution" not in inherited["tasks"][0]
    assert saved["durable_execution"] is True


def test_real_typescript_contract_and_python_mirror_agree():
    v2 = ROOT / "application" / "v2_ui"
    esbuild = v2 / "node_modules" / "esbuild" / "bin" / "esbuild"
    if not esbuild.exists():
        pytest.skip("The existing V2 build dependencies are not installed.")
    bundle = v2 / "node_modules" / ".cache-workflow-configuration-check.mjs"
    fixture = {
        "automatic": AUTOMATIC, "selected": SELECTED, "off": OFF,
        "recipient": RECIPIENT,
        "options": json.loads((ROOT / "functional_tests" / "fixtures" / "workflow_flow_authoring.json").read_text(encoding="utf-8"))["options"],
    }
    try:
        built = subprocess.run(
            ["node", str(esbuild), str(Path(__file__).with_suffix(".ts")), "--bundle", "--platform=node",
             "--format=esm", "--packages=external", f"--outfile={bundle}", "--log-level=error"],
            cwd=ROOT, text=True, capture_output=True, timeout=60,
        )
        assert built.returncode == 0, built.stderr
        checked = subprocess.run(
            ["node", str(bundle)], input=json.dumps(fixture), cwd=ROOT,
            text=True, capture_output=True, timeout=60,
        )
        assert checked.returncode == 0, checked.stderr
        output = json.loads(checked.stdout)
        for scope_name in ("personal", "group"):
            scope = {"type": scope_name, **({"groupId": GROUP_ID} if scope_name == "group" else {})}
            options = {"chat_execution": {"default": AUTOMATIC}}
            draft = editor.new_workflow_definition(scope, options)
            draft["name"] = "Digest"
            draft["tasks"][0].update(id="research", instructions="Research it.", chat_execution=SELECTED)
            expected = editor.workflow_for_save(draft, None, scope)
            assert output[scope_name] == expected
    finally:
        bundle.unlink(missing_ok=True)


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_workflow_storage_owners_accept_sdk_points_and_plain_query_rows(scope):
    harness = SaveParityHarness()
    module = harness.group if scope == "group" else harness.personal
    partition_field = "group_id" if scope == "group" else "user_id"
    partition = GROUP_ID if scope == "group" else OWNER_ID
    definitions = AtomicMemoryContainer(partition_field)
    runs = AtomicMemoryContainer(partition_field)
    items = AtomicMemoryContainer("run_id")
    conversations = AtomicMemoryContainer("id")
    for suffix, container in (("workflows", definitions), ("workflow_runs", runs), ("workflow_run_items", items)):
        setattr(module, f"cosmos_{scope}_{suffix}_container", container)
    module.cosmos_conversations_container = conversations
    saved = (
        module.save_group_workflow(partition, payload(), OWNER_ID)
        if scope == "group" else module.save_personal_workflow(partition, payload())
    )
    listed = getattr(module, f"get_{scope}_workflows")(partition)
    due = getattr(module, f"get_due_{scope}_workflows")()
    assert listed[0]["id"] == saved["id"]
    assert due[0]["id"] == saved["id"]
    assert type(listed[0]) is dict
    record = {
        "id": "run", "workflow_id": saved["id"], "conversation_id": "conversation",
        "started_at": "2026-10-16T19:00:00Z", "status": "completed",
    }
    written = getattr(module, f"save_{scope}_workflow_run")(partition, record)
    point = runs.read_item(item="run", partition_key=partition)
    loaded = getattr(module, f"get_{scope}_workflow_run")(partition, "run")
    history = getattr(module, f"list_{scope}_workflow_runs")(partition, saved["id"])
    latest = getattr(module, f"get_latest_{scope}_workflow_run_for_conversation")(partition, "conversation", saved["id"])
    missing = getattr(module, f"get_{scope}_workflow_run")("foreign-partition", "run")
    assert isinstance(point, CosmosDict)
    assert written == loaded == history[0] == latest
    assert type(loaded) is dict
    assert "_etag" not in loaded
    assert missing is None
    item = getattr(module, f"save_{scope}_workflow_run_item")(partition, {
        "id": "item", "run_id": "run", "type": "workflow_task", "reply": "The final result.",
    })
    item_point = items.read_item(item="item", partition_key="run")
    loaded_item = getattr(module, f"get_{scope}_workflow_run_item")("run", "item")
    item_history = getattr(module, f"list_{scope}_workflow_run_items")("run")
    assert isinstance(item_point, CosmosDict)
    assert item == loaded_item == item_history[0]
    hidden = items.upsert_item({"id": "hidden", "run_id": "run", "type": "workflow_result_chunk"})
    hidden_point = getattr(module, f"get_{scope}_workflow_run_item")("run", hidden["id"])
    public_items = getattr(module, f"list_{scope}_workflow_run_items")("run")
    assert hidden_point is None
    assert [row["id"] for row in public_items] == ["item"]
    conversation = {
        "id": "conversation", "user_id": OWNER_ID, "chat_type": "workflow",
        **({"group_id": GROUP_ID} if scope == "group" else {}),
    }
    conversations.upsert_item(conversation)
    normalize_conversation = getattr(module, f"_normalize_{scope}_workflow_conversation_id")
    selected = normalize_conversation(partition, {"conversation_id": conversation["id"]})
    assert selected == conversation["id"]
    conversations.upsert_item({**conversation, partition_field: "foreign"})
    with pytest.raises(PermissionError):
        normalize_conversation(partition, {"conversation_id": conversation["id"]})


def test_personal_guarded_run_save_preserves_sdk_point_metadata_and_conditional_writes():
    module = SaveParityHarness().personal
    runs = AtomicMemoryContainer("user_id")
    module.cosmos_personal_workflow_runs_container = runs
    seed = runs.upsert_item({
        "id": "run", "user_id": OWNER_ID, "chat_delivery": {"state": "delivered"},
        "cancellation_requested_at": "2026-10-16T19:00:00Z",
    })
    saved = module.save_personal_workflow_run(OWNER_ID, {
        "id": "run", "chat_delivery": {"state": "pending"}, "status": "completed",
    })
    current = runs.read_item(item="run", partition_key=OWNER_ID)
    assert saved["chat_delivery"] == {"state": "delivered"}
    assert saved["cancellation_requested_at"] == seed["cancellation_requested_at"]
    assert saved["status"] == "cancelling"
    assert isinstance(current, CosmosDict)
    assert current["_etag"] != seed["_etag"]
    assert "_etag" not in saved


def test_personal_workflow_count_owners_consume_scalar_query_rows(monkeypatch):
    module = SaveParityHarness().personal
    container = AtomicMemoryContainer("user_id")
    module.cosmos_personal_workflows_container = container
    captured = []

    def count_rows(*, query, parameters, partition_key):
        captured.append((query, parameters, partition_key))
        return iter([3])

    monkeypatch.setattr(container, "query_items", count_rows)
    ordinary = module.count_personal_orchestration_workflows(OWNER_ID)
    handoffs = module.count_personal_handoff_workflows_since(OWNER_ID, "2026-10-16T00:00:00Z")
    assert ordinary == handoffs == 3
    assert all(call[2] == OWNER_ID and "SELECT VALUE COUNT(1)" in call[0] for call in captured)


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-q"]))
