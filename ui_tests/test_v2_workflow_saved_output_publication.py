# test_v2_workflow_saved_output_publication.py
"""
Closed V2 List coverage for exact saved-record file publication.
Version: 0.261.119
Implemented in: 0.261.119

The real production SPA saves through production definition validation. Fictional
HTTP fixtures exercise scoped authoring, capability fallback, safe readback,
keyboard/mobile controls, and the existing authorized generated-file download.
No model, live workflow, or workspace publication is invoked.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# Shared closed fixtures configure repository-local, isolated application imports.
from ui_tests.fixtures.workflow_saved_output_publication import (
    ARTIFACT_BYTES,
    ARTIFACT_CONVERSATION_ID,
    ARTIFACT_FILE_NAME,
    GROUP_ID,
    SOURCE_CAPABILITIES,
    connect_options,  # noqa: F401
    execution_id,
    publication_key,
    publication_status,
    publication_task,
    saved_output_ui,  # noqa: F401
    use_saved_output,
)


pytestmark = pytest.mark.ui


def saved_workflow(ui, scope="user"):
    workflow_id = publication_key(scope)[1]
    records = ui.group_workflows[GROUP_ID] if scope == "group" else ui.personal_workflows
    return records[workflow_id]


def publication_fields(page):
    block = page.get_by_role("region", name="Publish artifact block", exact=True)
    block.get_by_text("Runner, inputs, references and outputs", exact=True).click()
    return block


def open_editor(ui, scope="user", **viewport):
    record = saved_workflow(ui, scope)
    record.pop("active_run_id", None)
    record.pop("status", None)
    ui.workflow_runs[record["id"]] = []
    if scope == "group":
        ui.open("/groups", **viewport)
        ui.page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
        ui.page.get_by_role("button", name=f"Edit {record['name']}", exact=True).click()
    else:
        ui.open(f"/workspace/workflows?workflow_id={record['id']}", **viewport)
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    return publication_fields(ui.page)


def source_field(block):
    return block.get_by_label("Publication source for Publish artifact", exact=True)


def format_field(block):
    return block.get_by_label("Publication format for Publish artifact", exact=True)


def input_field(block, name, index=1):
    return block.get_by_label(f"Publish artifact inputs input {index} {name}", exact=True)


def policy_field(block):
    return block.get_by_label("Complete publication when for Publish artifact", exact=True)


def save_editor(ui):
    ui.page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    return ui.workflow_writes[-1]


def reopen_editor(ui, scope="user"):
    ui.page.get_by_role("button", name=f"Edit {saved_workflow(ui, scope)['name']}", exact=True).click()
    return publication_fields(ui.page)


def assert_no_execution(ui):
    assert not any("/runtime/" in request.path or request.path.endswith(("/run", "/publish", "/promote"))
                   for request in ui.writes)


@pytest.mark.parametrize("scope", ["user", "group"])
@pytest.mark.parametrize("source,producer,output", [
    ("native_analysis", "analyze", "authoritative"),
    ("saved_output", "collect-findings", "records"),
    ("saved_output", "output-join", "selected_records"),
    ("saved_output", "saved-records", "authoritative"),
])
def test_both_sources_save_reopen_with_exact_records_producers(saved_output_ui, scope, source, producer, output):
    ui, page = saved_output_ui, saved_output_ui.page
    original = copy.deepcopy(saved_workflow(ui, scope))
    block = open_editor(ui, scope)
    source_field(block).select_option(source)
    input_field(block, "producer").select_option(producer)
    input_field(block, "output").select_option(output)
    input_field(block, "name").fill("deliverable")
    policy_field(block).select_option("approved")
    expected_format = "json" if source == "saved_output" else "csv"
    format_field(block).select_option(expected_format)
    for destination, identifier in (("public", "public-handbook"), ("group", GROUP_ID), ("personal", None)):
        block.get_by_label("Publication scope for Publish artifact", exact=True).select_option(destination)
        if identifier:
            block.get_by_label("Publication workspace ID for Publish artifact", exact=True).fill(identifier)
        expect(source_field(block)).to_have_value(source)
        expect(policy_field(block)).to_have_value("approved")
    if scope == "group":
        block.get_by_label("Publication scope for Publish artifact", exact=True).select_option("group")
        block.get_by_label("Publication workspace ID for Publish artifact", exact=True).fill(GROUP_ID)
    if source == "saved_output":
        expect(format_field(block).locator("option:checked")).to_have_text("JSON - exact saved records")
        expect(format_field(block).locator('option[value="md"]')).to_have_attribute("disabled", "")
        expect(format_field(block).locator('option[value="csv"]')).to_have_attribute("disabled", "")
        expect(input_field(block, "producer").locator('option[value="analyze"]')).to_have_count(0)
        expect(input_field(block, "kind")).to_have_value("records")
        expect(block.get_by_text("without rerunning analysis.", exact=False)).to_be_visible()
        expect(block.get_by_role("button", name="Add publish artifact inputs input", exact=True)).to_be_disabled()
    write = save_editor(ui)
    task = publication_task(write.body)
    assert task["publication"] == {
        "source_kind": source, "artifact_format": expected_format,
        "workspace_scope": "group" if scope == "group" else "personal",
        "completion_policy": "approved", **({"group_id": GROUP_ID} if scope == "group" else {}),
    }
    assert task["inputs"] == [{
        "name": "deliverable",
        "source": {"kind": "node_output", "node_id": producer, "output": output, "scope": "current"},
        "required": True, "expected_kind": "records" if source == "saved_output" else "json",
        "allow_partial": False,
    }]
    assert task["runner"]["type"] == "inherit" and not task["runner"].get("model_id")
    assert task["document_action"] == {"type": "none"}
    assert write.query.get("group_id") == ([GROUP_ID] if scope == "group" else None)
    assert write.body["flow"] == original["flow"]
    block = reopen_editor(ui, scope)
    expect(source_field(block)).to_have_value(source)
    expect(format_field(block)).to_have_value(expected_format)
    expect(policy_field(block)).to_have_value("approved")
    expect(input_field(block, "producer")).to_have_value(producer)
    expect(input_field(block, "output")).to_have_value(output)
    reopened_task = publication_task(save_editor(ui).body)
    assert reopened_task["publication"] == task["publication"]
    assert reopened_task["inputs"] == task["inputs"]
    assert_no_execution(ui)


@pytest.mark.parametrize("scope", ["user", "group"])
@pytest.mark.parametrize("advertised", [True, False])
def test_omitted_source_and_policy_stay_omitted_with_native_controls(saved_output_ui, scope, advertised):
    ui = saved_output_ui
    publication = publication_task(saved_workflow(ui, scope))["publication"]
    publication.pop("completion_policy")
    if not advertised:
        ui.publication_sources = None
        ui.publication_policies = None
    block = open_editor(ui, scope)
    expect(source_field(block)).to_have_value("native_analysis")
    expect(policy_field(block)).to_have_value("")
    if not advertised:
        expect(source_field(block).locator('option[value="saved_output"]')).to_have_attribute("disabled", "")
        expect(policy_field(block)).to_be_disabled()
        expect(block.get_by_text("This server does not advertise", exact=False)).to_be_visible()
    for value in ("json", "md", "csv"):
        format_field(block).select_option(value)
        expect(format_field(block)).to_have_value(value)
    block.get_by_label("Instructions", exact=True).fill("Preserve the existing source behavior.")
    expected = {**publication, "artifact_format": "csv"}
    assert publication_task(save_editor(ui).body)["publication"] == expected
    block = reopen_editor(ui, scope)
    expect(source_field(block)).to_have_value("native_analysis")
    expect(policy_field(block)).to_have_value("")
    assert publication_task(save_editor(ui).body)["publication"] == expected


def test_explicit_native_source_remains_supported_by_an_older_server(saved_output_ui):
    ui = saved_output_ui
    task = publication_task(saved_workflow(ui))
    task["publication"]["source_kind"] = "native_analysis"
    task["publication"].pop("completion_policy")
    original = copy.deepcopy(task["publication"])
    ui.publication_sources = None
    ui.publication_policies = None
    block = open_editor(ui)
    expect(source_field(block)).to_have_value("native_analysis")
    block.get_by_label("Instructions", exact=True).fill("Keep the explicit native Analyze source.")
    assert publication_task(save_editor(ui).body)["publication"] == original


def test_future_capabilities_never_enable_unimplemented_saved_formats(saved_output_ui):
    ui = saved_output_ui
    ui.publication_sources.extend([{
        "source_kind": "future_source", "output_kinds": ["records"], "artifact_formats": ["pdf"],
    }])
    ui.publication_sources[1]["artifact_formats"].extend(["csv", "md", "pdf", "docx", "pptx"])
    block = open_editor(ui)
    expect(source_field(block).locator('option[value="future_source"]')).to_have_count(0)
    source_field(block).select_option("saved_output")
    expect(format_field(block).locator("option:enabled")).to_have_count(1)
    expect(format_field(block).locator("option:enabled")).to_have_text("JSON - exact saved records")
    input_field(block, "producer").select_option("saved-records")
    assert publication_task(save_editor(ui).body)["publication"]["artifact_format"] == "json"


def test_switching_back_to_native_keeps_completion_and_requires_explicit_native_input(saved_output_ui):
    ui = saved_output_ui
    record = use_saved_output(saved_workflow(ui))
    original_flow = copy.deepcopy(record["flow"])
    block = open_editor(ui)
    policy_field(block).select_option("approved")
    input_field(block, "allow partial").check()
    source_field(block).select_option("native_analysis")
    expect(policy_field(block)).to_have_value("approved")
    expect(input_field(block, "producer")).to_have_value("collect-findings")
    expect(input_field(block, "allow partial")).to_be_checked()
    expect(format_field(block).locator("option:enabled")).to_have_count(3)
    input_field(block, "producer").select_option("analyze")
    format_field(block).select_option("md")
    task = publication_task(save_editor(ui).body)
    assert task["publication"]["source_kind"] == "native_analysis"
    assert task["publication"]["completion_policy"] == "approved"
    assert task["inputs"][0]["source"]["node_id"] == "analyze"
    assert task["inputs"][0]["allow_partial"] is True
    assert saved_workflow(ui)["flow"] == original_flow


@pytest.mark.parametrize("policies", [["submitted", "approved", "indexed_ready"], None, ["approved"]])
def test_enabling_publication_never_defaults_to_saved_output_or_invents_a_policy(saved_output_ui, policies):
    ui = saved_output_ui
    publication_task(saved_workflow(ui)).pop("publication")
    ui.publication_policies = policies
    block = open_editor(ui)
    block.get_by_text("Publish a workflow file", exact=True).click()
    expect(source_field(block)).to_have_value("native_analysis")
    expect(format_field(block)).to_have_value("md")
    expected_policy = "submitted" if policies and "submitted" in policies else ""
    expect(policy_field(block)).to_have_value(expected_policy)
    source_field(block).select_option("saved_output")
    input_field(block, "producer").select_option("collect-findings")
    input_field(block, "output").select_option("records")
    publication = publication_task(save_editor(ui).body)["publication"]
    assert publication["source_kind"] == "saved_output"
    assert publication["artifact_format"] == "json"
    if expected_policy:
        assert publication["completion_policy"] == expected_policy
    else:
        assert "completion_policy" not in publication


@pytest.mark.parametrize("capabilities", [
    None,
    [],
    [SOURCE_CAPABILITIES[0]],
    [{"source_kind": "saved_output", "output_kinds": ["json"], "artifact_formats": ["json"]}],
    [{"source_kind": "saved_output", "output_kinds": ["records"], "artifact_formats": ["csv"]}],
])
def test_saved_source_without_advertised_profile_stays_read_only(saved_output_ui, capabilities):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui))
    original = copy.deepcopy(record)
    ui.publication_sources = capabilities
    block = open_editor(ui)
    expect(page.get_by_role("alert").filter(has_text="does not support the saved workflow output")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    expect(page.get_by_label("Workflow name", exact=True)).to_be_disabled()
    expect(source_field(block)).to_have_value("saved_output")
    expect(format_field(block)).to_have_value("json")
    expect(format_field(block)).to_be_disabled()
    assert record["tasks"] == original["tasks"] and record["flow"] == original["flow"]
    assert not ui.workflow_writes


@pytest.mark.parametrize("source", [None, "", "future_source", {"kind": "saved_output"}, ["saved_output"]])
def test_unknown_saved_source_is_preserved_not_coerced(saved_output_ui, source):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui))
    publication_task(record)["publication"]["source_kind"] = copy.deepcopy(source)
    original = copy.deepcopy(publication_task(record))
    open_editor(ui)
    expect(page.get_by_role("alert").filter(has_text="unsupported source kind")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert publication_task(record) == original
    assert not ui.workflow_writes


@pytest.mark.parametrize("field", ["profile", "generated_artifact_source"])
def test_unknown_publication_fields_preserve_read_only_without_leaking_values(saved_output_ui, field):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui))
    publication_task(record)["publication"][field] = {"private": "private-lineage-marker"}
    original = copy.deepcopy(publication_task(record))
    open_editor(ui)
    expect(page.get_by_role("alert").filter(has_text="unsupported fields")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    expect(page.get_by_text("private-lineage-marker", exact=False)).to_have_count(0)
    assert publication_task(record) == original
    assert not ui.workflow_writes


@pytest.mark.parametrize("version,durable", [(2, True), (3, False)])
def test_saved_output_requires_v3_durable_without_down_conversion(saved_output_ui, version, durable):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui))
    publication_task(record)["publication"].pop("completion_policy")
    record.update(definition_version=version, durable_execution=durable)
    original = copy.deepcopy(record)
    open_editor(ui) if version == 3 else ui.open(f"/workspace/workflows?workflow_id={record['id']}")
    expect(page.get_by_role("alert").filter(has_text="durable definition-v3")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert record["tasks"] == original["tasks"]
    assert record["definition_version"] == version and record["durable_execution"] == durable
    assert not ui.workflow_writes


@pytest.mark.parametrize("format_name", ["md", "csv", "docx", "pdf", "pptx", "xml", "future_format", None])
def test_unsupported_saved_format_stays_read_only_without_json_fallback(saved_output_ui, format_name):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui))
    publication_task(record)["publication"]["artifact_format"] = format_name
    original = copy.deepcopy(publication_task(record))
    open_editor(ui)
    expect(page.get_by_role("alert").filter(has_text="unsupported source/format combination")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert publication_task(record) == original
    assert not ui.workflow_writes


@pytest.mark.parametrize("kind", ["text", "json", "document_results", "any"])
def test_wrong_producer_kind_is_unavailable_and_cannot_save(saved_output_ui, kind):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui), "saved-records", "authoritative")
    task = next(task for task in record["tasks"] if task["id"] == "records-task")
    task["output_contract"] = {"kind": kind, "allow_partial": False, "require_complete_coverage": False}
    # Keep the unrelated join valid while testing the explicit publishing input.
    record["flow"]["nodes"][-2]["join"]["exports"][0]["else"] = {"node_id": "collect-findings", "output": "records"}
    block = open_editor(ui)
    expect(input_field(block, "producer").locator('option[value="saved-records"]')).to_have_attribute("disabled", "")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="exactly one required saved records")).to_be_visible()
    assert not ui.workflow_writes
    input_field(block, "producer").select_option("collect-findings")
    input_field(block, "output").select_option("records")
    assert publication_task(save_editor(ui).body)["inputs"][0]["source"]["node_id"] == "collect-findings"


@pytest.mark.parametrize("invalid", ["missing", "multiple", "optional", "any", "loop_item", "diagnostics", "undeclared"])
def test_saved_publication_binding_must_be_one_required_explicit_records_output(saved_output_ui, invalid):
    ui, page = saved_output_ui, saved_output_ui.page
    task = publication_task(use_saved_output(saved_workflow(ui)))
    binding = task["inputs"][0]
    if invalid == "missing":
        task["inputs"] = []
    elif invalid == "multiple":
        task["inputs"].append({**copy.deepcopy(binding), "name": "second"})
    elif invalid == "optional":
        binding["required"] = False
    elif invalid == "any":
        binding["expected_kind"] = "any"
    elif invalid == "loop_item":
        binding.update(source={"kind": "loop_item", "loop_id": "each-source", "scope": "current"}, expected_kind="json")
    else:
        binding["source"]["output"] = invalid
    original = copy.deepcopy(task)
    block = open_editor(ui)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="exactly one required saved records")).to_be_visible()
    if invalid == "loop_item":
        expect(input_field(block, "source").locator('option[value="loop_item"]')).to_have_attribute("disabled", "")
    assert task == original and not ui.workflow_writes


def test_mixed_join_cannot_disguise_a_scalar_as_records(saved_output_ui):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui), "output-join", "selected_records")
    record["flow"]["nodes"][-2]["join"]["exports"][0]["else"] = {"node_id": "analyze", "output": "json"}
    block = open_editor(ui)
    expect(input_field(block, "producer").locator('option[value="output-join"]')).to_have_attribute("disabled", "")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="exactly one required saved records")).to_be_visible()
    assert not ui.workflow_writes


@pytest.mark.parametrize("availability", ["skipped", "later", "missing"])
def test_saved_output_does_not_weaken_reachability_or_required_producer_checks(saved_output_ui, availability):
    ui, page = saved_output_ui, saved_output_ui.page
    record = use_saved_output(saved_workflow(ui), "saved-records", "records")
    nodes = record["flow"]["nodes"]
    nodes[-2]["join"]["exports"][0]["else"] = {"node_id": "collect-findings", "output": "records"}
    if availability == "skipped":
        nodes[1]["run_when"] = {"op": "eq", "left": {"literal": False}, "right": {"literal": True}}
        error = "requires an output that can be skipped"
    elif availability == "later":
        nodes.append(nodes.pop(1))
        error = "earlier, reachable producer"
    else:
        publication_task(record)["inputs"][0]["source"]["node_id"] = "missing-producer"
        error = "missing producer or undeclared output"
    open_editor(ui)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=error)).to_be_visible()
    assert not ui.workflow_writes


@pytest.mark.parametrize("scope", ["user", "group"])
def test_existing_explicit_partial_acceptance_round_trips_without_new_policy(saved_output_ui, scope):
    ui = saved_output_ui
    record = use_saved_output(saved_workflow(ui, scope))
    body_task = next(task for task in record["tasks"] if task["id"] == "analyze-task")
    body_task["output_contract"].update(allow_partial=True, require_complete_coverage=False)
    loop = record["flow"]["nodes"][2]
    collect = record["flow"]["nodes"][3]
    loop["body"]["outputs"][0]["allow_partial"] = True
    collect["output_contract"].update(allow_partial=True, require_complete_coverage=False)
    original_flow = copy.deepcopy(record["flow"])
    block = open_editor(ui, scope)
    input_field(block, "allow partial").check()
    policy_field(block).select_option("")
    task = publication_task(save_editor(ui).body)
    assert task["inputs"][0]["allow_partial"] is True
    assert "completion_policy" not in task["publication"]
    assert saved_workflow(ui, scope)["flow"] == original_flow
    block = reopen_editor(ui, scope)
    expect(input_field(block, "allow partial")).to_be_checked()
    expect(policy_field(block)).to_have_value("")


@pytest.mark.parametrize("scope,width,theme", [("user", 1280, "light"), ("group", 390, "dark")])
def test_list_keyboard_source_join_and_completion_controls_fit_viewport(saved_output_ui, scope, width, theme):
    ui, page = saved_output_ui, saved_output_ui.page
    original = copy.deepcopy(saved_workflow(ui, scope))
    block = open_editor(ui, scope, width=width, height=844, theme=theme)
    source = source_field(block)
    source.focus()
    source.press("End")
    expect(source).to_have_value("saved_output")
    producer = input_field(block, "producer")
    producer.focus()
    producer.press("End")
    expect(producer).to_have_value("output-join")
    expect(input_field(block, "output")).to_have_value("selected_records")
    policy = policy_field(block)
    policy.focus()
    policy.press("ArrowUp")
    expect(policy).to_have_value("approved")
    ui.assert_no_overflow()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    assert dialog.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    for control in (source, producer, format_field(block), policy):
        control.scroll_into_view_if_needed()
        box = control.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
    save = page.get_by_role("button", name="Save workflow", exact=True)
    save.focus()
    save.press("Enter")
    expect(dialog).to_have_count(0)
    payload = ui.workflow_writes[-1].body
    assert payload["flow"] == original["flow"]
    assert [task["id"] for task in payload["tasks"]] == [task["id"] for task in original["tasks"]]
    assert publication_task(payload)["publication"]["source_kind"] == "saved_output"
    assert_no_execution(ui)


@pytest.mark.parametrize("capabilities", [
    None,
    {},
    [{"source_kind": "saved_output", "output_kinds": "records", "artifact_formats": ["json"]}],
    [{"source_kind": "saved_output", "output_kinds": ["records"], "artifact_formats": None}],
    [SOURCE_CAPABILITIES[1], SOURCE_CAPABILITIES[1]],
])
def test_malformed_publication_capabilities_fail_closed(saved_output_ui, capabilities):
    ui, page = saved_output_ui, saved_output_ui.page
    ui.option_overrides["publication_source_capabilities"] = capabilities
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Edit Publication workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="invalid publication source capabilities")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert not ui.workflow_writes


@pytest.mark.parametrize("scope,state", [("user", "indexed_ready"), ("group", "unavailable")])
def test_saved_export_keeps_exact_attempt_completion_and_unavailable_readback(saved_output_ui, scope, state):
    ui, page = saved_output_ui, saved_output_ui.page
    destination = "group" if scope == "group" else "personal"
    status = publication_status(
        destination, state=state, policy_satisfied=state == "indexed_ready",
        approval="approved" if scope == "group" else "not_required",
        processing="complete" if state == "indexed_ready" else "unavailable",
        screening="available", index="ready" if state == "indexed_ready" else "unavailable",
        reason_code=f"publication_{state}", retryable=False,
        unresolved_stages=[] if state == "indexed_ready" else ["processing"],
    )
    ui.set_publication_status(status, scope=scope, attempt=2)
    use_saved_output(saved_workflow(ui, scope))
    key = publication_key(scope)
    eid = execution_id(key[1], key[2], "publish")
    for item in (ui.execution_pages[key][""]["items"][0], ui.attempt_pages[(*key, eid)][""]["items"][0]):
        item["workflow_validation"] = {
            "version": 1, "status": "accepted_partial", "counts": {"records": 2},
            "reason_codes": ["partial_output_accepted"],
        }
    ui.open("/groups" if scope == "group" else "/workspace/workflows", width=390, height=844)
    if scope == "group":
        page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
    row = page.get_by_role("listitem").filter(has_text=saved_workflow(ui, scope)["name"]).first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    page.get_by_role("button", name=f"Show execution attempts for {eid}", exact=True).click()
    details = page.get_by_role("region", name=f"Publication for execution {eid} attempt 2", exact=True)
    expect(details).to_contain_text(status["id"])
    expect(page.get_by_text("accepted_partial", exact=False).first).to_be_visible()
    if state == "indexed_ready":
        expect(details).to_contain_text("Saved completion observation: Publication indexed and ready")
        page.get_by_role("button", name="Load authoritative output excerpt", exact=True).click()
        expect(page.locator("pre").filter(has_text='"attempt":2')).to_be_visible()
    else:
        expect(details).to_contain_text("unavailable")
        expect(page.get_by_role("button", name="Retry task", exact=True)).to_have_count(0)
    expect(page.get_by_text("generated_artifact_source", exact=False)).to_have_count(0)
    assert not any(".blob." in (request.path or "") for request in ui.requests)
    ui.assert_no_overflow()
    assert_no_execution(ui)


@pytest.mark.parametrize("row_count,validation", [(2, "valid"), (0, "valid"), (2, "accepted_partial")])
def test_saved_output_uses_existing_generated_file_card_and_authorized_download(saved_output_ui, row_count, validation):
    ui, page = saved_output_ui, saved_output_ui.page
    summary = f"{row_count} exact saved records ({validation})"
    artifact = ui.messages[ARTIFACT_CONVERSATION_ID][0]["metadata"]["generated_tabular_outputs"][0]
    artifact.update(row_count=row_count, summary=summary)
    ui.artifact_bytes = b"[]" if row_count == 0 else ARTIFACT_BYTES
    ui.open(f"/chat?conversation_id={ARTIFACT_CONVERSATION_ID}", width=390, height=844)
    expect(page.get_by_text("Generated JSON export", exact=True)).to_be_visible()
    expect(page.get_by_text(f"{row_count} rows", exact=True)).to_be_visible()
    expect(page.get_by_text(summary, exact=True)).to_be_visible()
    expect(page.get_by_text(re.compile(r"^Analyze .* artifact$"))).to_have_count(0)
    expect(page.get_by_text("generated_artifact_source", exact=False)).to_have_count(0)
    button = page.get_by_role("button", name="Download JSON", exact=True)
    button.scroll_into_view_if_needed()
    button.focus()
    with page.expect_download() as pending:
        button.press("Enter")
    download = pending.value
    assert download.suggested_filename == ARTIFACT_FILE_NAME
    artifact_path = ROOT / "ui_tests" / "artifacts" / "saved-output-publication-download.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        download.save_as(artifact_path)
        assert artifact_path.read_bytes() == ui.artifact_bytes
    finally:
        artifact_path.unlink(missing_ok=True)
    assert len(ui.artifact_downloads) == 1
    ui.assert_no_overflow()
    assert_no_execution(ui)


@pytest.mark.parametrize("capability,row_source", [
    ("file_export", "function_result"), ("file_export", None), ("tabular", "saved_records"),
])
def test_other_compact_exports_keep_existing_summary_behavior(saved_output_ui, capability, row_source):
    ui, page = saved_output_ui, saved_output_ui.page
    artifact = ui.messages[ARTIFACT_CONVERSATION_ID][0]["metadata"]["generated_tabular_outputs"][0]
    artifact.update(capability=capability, row_source=row_source)
    ui.open(f"/chat?conversation_id={ARTIFACT_CONVERSATION_ID}")
    expect(page.get_by_text("Generated JSON export", exact=True)).to_be_visible()
    expect(page.get_by_text(artifact["summary"], exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Download JSON", exact=True)).to_be_visible()


def test_saved_record_card_summary_is_inert_text(saved_output_ui):
    ui, page = saved_output_ui, saved_output_ui.page
    artifact = ui.messages[ARTIFACT_CONVERSATION_ID][0]["metadata"]["generated_tabular_outputs"][0]
    artifact["summary"] = '<img src="/private-record-source" onerror="window.savedOutputInjected=true"> 2 exact saved records'
    ui.open(f"/chat?conversation_id={ARTIFACT_CONVERSATION_ID}")
    expect(page.get_by_text(artifact["summary"], exact=True)).to_be_visible()
    expect(page.locator('img[src="/private-record-source"]')).to_have_count(0)
    assert page.evaluate("window.savedOutputInjected === undefined")
    assert not any(request.path == "/private-record-source" for request in ui.requests)
