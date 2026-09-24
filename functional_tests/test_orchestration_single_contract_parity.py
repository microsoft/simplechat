# test_orchestration_single_contract_parity.py
"""Gather/Reason/Render parity with the answer features legacy orchestration had.

Version: 0.261.134
Implemented in: 0.261.134

Uses the initialized headless harness (real bootstrap, model resolution, leases,
checkpoints, retained results and renderer) with offline model replies. Covers:
Auto model routing on dependency plans, saved memory and conversation references in
compose, the declared knowledge basis, optional inputs that let an answer disclose a
failed gather step instead of failing, planner-named visuals, the planner descriptor,
web search failure classification with one transient retry, and Foundry citation
placeholders turned into links.
"""

import importlib
import importlib.util
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions

from functions_orchestration_execution import HarnessExecutionError
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import (
    compose_step, decoded_frames, input_binding, render_step,
)
from test_support.versioning import assert_app_version_at_least


ROUTED = "routed-writer"


def _routing_candidates(settings, deployments):
    catalog = importlib.import_module("functions_model_catalog")
    rows = []
    for model in settings["gpt_model"]["selected"]:
        if model["deploymentName"] not in deployments:
            continue
        metadata = catalog.apply_model_profile(model, {}, settings)
        rows.append({
            "key": model["deploymentName"], "label": model["deploymentName"],
            "selection": {"model_deployment": model["deploymentName"], "model_provider": "aoai"},
            "profile": metadata["_catalog_profile"], "capabilities": metadata["capabilities"],
            "effective_revision": metadata["_catalog_effective_revision"],
        })
    return rows


def _add_routed_model(harness):
    harness.settings["gpt_model"]["selected"].append({
        "deploymentName": ROUTED, "modelName": "gpt-4o", "responseLength": 1024,
    })
    return _routing_candidates(harness.settings, {ROUTED})


def _replace_plan(harness, update):
    current = harness.read()
    update(current["plan"])
    harness.runs.replace_item(
        item="run-1", body=current, etag=current["_etag"], match_condition=MatchConditions.IfNotModified,
    )


def _saved_steps(harness):
    """The durable step records, not the checkpoint manifests stored beside them."""
    return {
        record["step_id"]: record for record in harness.steps.items.values()
        if record.get("run_id") == "run-1" and record.get("step_id") and "status" in record
    }


def _compose_messages(harness, index=-1):
    return harness.model_calls[index]["messages"]


def _compose_payload(harness, index=-1):
    return json.loads(_compose_messages(harness, index)[-1]["content"])


def _mixed_compose(step_id="prepare", *, inputs=None, visuals=None, basis="sources_and_general_knowledge"):
    step = compose_step(step_id, inputs=inputs)
    step["arguments"] = {
        "instruction": "Write the requested report.", "knowledge_basis": basis,
        **({"visuals": visuals} if visuals else {}),
    }
    return step


def test_version_includes_single_contract_parity():
    assert_app_version_at_least("0.261.134")


# ------------------------------------------------------------------------------------------
# Auto model routing
# ------------------------------------------------------------------------------------------

def test_dependency_planning_binds_auto_models_and_records_the_planner(harness, monkeypatch):
    candidates = _add_routed_model(harness)
    monkeypatch.setattr(harness.planner, "authorized_routing_candidates", lambda settings, user_id: candidates)
    harness.replies = [json.dumps({
        "kind": "plan", "intent": {"summary": "List the states and capitals.", "complexity": "simple"},
        "assumptions": [],
        "steps": [{
            "step_id": "prepare", "capability_id": "compose", "title": "Prepare state capitals",
            "arguments": {"instruction": "List every U.S. state with its capital.",
                          "knowledge_basis": "general_knowledge"},
            "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}], "model_task": "general",
        }],
        "final_response": input_binding("prepare"),
    })]

    kind, plan = harness.planner.plan_request(
        "create a csv showing the states and their capitals", {}, "conversation-1", "owner",
        settings=harness.settings, seeds={"model_routing": "auto"}, contract_version=2,
    )

    assert kind == "plan"
    assert plan["model_routing"] == "auto"
    assert plan["steps"][0]["model_binding"]["selection"]["model_deployment"] == ROUTED
    assert plan["planner"] == {"label": "gpt-4o", "source": "default"}
    system = harness.model_calls[0]["messages"][0]["content"]
    assert "When model_routing is auto" in system
    assert "knowledge_basis" in system and "render_file" in system


def test_auto_routed_dependency_plan_runs_compose_on_its_bound_model(harness):
    candidates = _add_routed_model(harness)
    assign = importlib.import_module("functions_orchestration_model_routing").assign_step_models
    harness.create(replies=["The routed answer."], final_response=input_binding("prepare"))
    _replace_plan(harness, lambda plan: assign(plan, candidates))

    progress = []
    harness.prepare().execute(emit=progress.append)
    frames = decoded_frames(progress)
    saved = harness.read()

    assert saved["status"] == "completed", saved.get("failure")
    assert [call["model"] for call in harness.model_calls] == [ROUTED]
    step_events = [
        frame for frame in frames if frame.get("type") == "orchestration_step" and frame.get("step_id") == "prepare"
    ]
    completed = [event for event in step_events if event.get("status") == "completed"]
    assert completed and completed[-1]["model_binding"]["selection"]["model_deployment"] == ROUTED
    record = _saved_steps(harness)["prepare"]
    assert record["model_binding"]["selection"]["model_deployment"] == ROUTED
    assert all(client.closed for client in harness.clients)


def test_auto_plan_with_a_changed_profile_fails_closed_before_any_model_call(harness):
    candidates = _add_routed_model(harness)
    assign = importlib.import_module("functions_orchestration_model_routing").assign_step_models
    harness.create(replies=["Must not be generated."], final_response=input_binding("prepare"))

    def stale(plan):
        assign(plan, candidates)
        plan["steps"][0]["model_binding"]["profile_revision"] = "stale-revision"

    _replace_plan(harness, stale)
    record, lease = harness.claim()
    with pytest.raises(HarnessExecutionError) as failure:
        harness.execution.prepare_harness_execution(record, settings=harness.settings, lease=lease)

    assert failure.value.code == "model_routing_changed"
    assert harness.model_calls == []
    assert harness.read()["failure"]["code"] == "model_routing_changed"


def test_plan_edits_rebind_auto_models_instead_of_dropping_auto_routing(harness, monkeypatch):
    editing = importlib.import_module("functions_orchestration_plan_editing")
    routing = importlib.import_module("functions_orchestration_model_routing")
    candidates = _add_routed_model(harness)
    monkeypatch.setattr(editing, "authorized_routing_candidates", lambda settings, user_id: candidates)
    record = harness.create(final_response=input_binding("prepare"))
    plan = deepcopy(record["plan"])
    routing.assign_step_models(plan, candidates)
    context = {
        "conversation_id": "conversation-1", "turn_id": "turn-1",
        "user_message": harness.turn["content"],
        "seeds": {"model_routing": "auto"}, "planner_contract_version": 2,
    }

    checked = editing.validate_edited_plan(plan, context, "owner", harness.settings, {"user_roles": []})

    assert checked["model_routing"] == "auto"
    assert checked["steps"][0]["model_binding"]["selection"]["model_deployment"] == ROUTED
    monkeypatch.setattr(editing, "authorized_routing_candidates", lambda settings, user_id: [])
    with pytest.raises(editing.PlanRevisionError) as failure:
        editing.validate_edited_plan(plan, context, "owner", harness.settings, {"user_roles": []})
    assert failure.value.code == "model_unavailable"


def test_answer_selection_prefers_the_final_response_producer():
    routing = importlib.import_module("functions_orchestration_model_routing")
    binding = {"selection": {"model_deployment": "writer"}, "group_id": None}
    plan = {
        "model_routing": "auto", "planner_contract_version": 2,
        "final_response": input_binding("answer"),
        "steps": [
            {"step_id": "records", "capability_id": "compose", "model_binding": {
                "selection": {"model_deployment": "records-model"}, "group_id": None}},
            {"step_id": "answer", "capability_id": "compose", "model_binding": binding},
        ],
    }
    assert routing.answer_selection(plan, {})["model"] == {"model_deployment": "writer"}
    render_only = {"model_routing": "auto", "planner_contract_version": 2, "steps": [
        {"step_id": "file", "capability_id": "render_file"},
    ]}
    assert routing.answer_selection(render_only, {"model": {"model_deployment": "default"}}) == {
        "model": {"model_deployment": "default"},
    }


# ------------------------------------------------------------------------------------------
# Compose: knowledge basis, memory and conversation references
# ------------------------------------------------------------------------------------------

def test_compose_follows_the_declared_general_knowledge_basis(harness):
    composition = importlib.import_module("functions_orchestration_composition")
    step = compose_step()
    step["arguments"]["knowledge_basis"] = "general_knowledge"
    harness.create([step], replies=["Alabama,Montgomery"], final_response=input_binding("prepare"))

    harness.prepare().execute()

    policy = _compose_messages(harness)[0]["content"]
    assert composition.KNOWLEDGE_POLICIES["general_knowledge"] in policy
    assert "Every factual claim must come from the named inputs" not in policy
    assert harness.read()["status"] == "completed"


def test_compose_defaults_to_general_knowledge_without_inputs_and_sources_with_them(harness):
    composition = importlib.import_module("functions_orchestration_composition")
    harness.create(
        [compose_step("facts", outputs=[{"name": "answer", "kind": "text-v1"}]),
         compose_step("prepare", inputs={"facts": {"binding": input_binding("facts"), "allow_partial": False}})],
        replies=["A retained fact.", "An answer from the fact."], final_response=input_binding("prepare"),
    )

    harness.prepare().execute()

    assert composition.KNOWLEDGE_POLICIES["general_knowledge"] in _compose_messages(harness, 0)[0]["content"]
    assert composition.KNOWLEDGE_POLICIES["sources"] in _compose_messages(harness, 1)[0]["content"]


def test_compose_receives_saved_memory_and_resolved_conversation_references(harness, monkeypatch):
    composition = importlib.import_module("functions_orchestration_composition")
    original = harness.execution.load_orchestration_memory
    memory_text = "<Instruction Memory>\nAlways write in British English."

    def with_instruction(*args, **kwargs):
        memory = original(*args, **kwargs)
        return {**memory, "context_messages": [{"role": "system", "content": memory_text}]}

    monkeypatch.setattr(harness.execution, "load_orchestration_memory", with_instruction)
    history = [
        {"id": "user-prior", "conversation_id": "conversation-1", "role": "user",
         "content": "Which wineries are near Walla Walla?", "timestamp": "2026-09-21T17:00:00+00:00"},
        {"id": "assistant-prior", "conversation_id": "conversation-1", "role": "assistant",
         "content": "L'Ecole No 41 and Woodward Canyon.", "timestamp": "2026-09-21T17:01:00+00:00"},
    ]
    harness.create(
        replies=["| Winery |\n| --- |\n| L'Ecole No 41 |"], final_response=input_binding("prepare"),
        history=history, request_resolution={
            "relationship": "follow_up", "resolved_message": "Put those wineries in a table.",
            "message_ids": ["user-prior", "assistant-prior"], "requires_retrieval": False,
            "clarification": "",
        },
    )

    harness.prepare().execute()
    messages = _compose_messages(harness)

    assert {"role": "system", "content": memory_text} in messages
    assert {"role": "system", "content": composition.CONVERSATION_POLICY} in messages
    assert {"role": "assistant", "content": "L'Ecole No 41 and Woodward Canyon."} in messages
    # Reference data precedes the request; the request is still the final message.
    assert json.loads(messages[-1]["content"])["instruction"] == "Prepare the complete requested content."


# ------------------------------------------------------------------------------------------
# Optional inputs: a failed gather step is disclosed instead of failing the answer
# ------------------------------------------------------------------------------------------

def _failing_search(harness, monkeypatch, failure_code="provider_failed", calls=None):
    executor = importlib.import_module("functions_orchestration_executor")
    schema = importlib.import_module("functions_orchestration_schema")
    calls = [] if calls is None else calls
    original = executor._dependency_adapter

    def failing(step, context, **kwargs):
        calls.append(step["step_id"])
        failure = schema.build_failure(failure_code)
        return schema.build_step_result(
            status=schema.STEP_STATUS_FAILED, failure=failure, summary=failure["message"],
            error=failure["message"],
        )

    monkeypatch.setattr(
        executor, "_dependency_adapter",
        lambda capability_id: failing if capability_id == "web_search" else original(capability_id),
    )
    monkeypatch.setattr(executor, "_TRANSIENT_RETRY_DELAY_SECONDS", 0)
    harness.settings["enable_web_search"] = True
    return calls


def _search_step():
    return {"step_id": "search", "capability_id": "web_search", "arguments": {
        "query": "First three presidents of the United States terms of office",
    }}


def test_failed_optional_search_is_retried_once_then_disclosed_by_the_answer(harness, monkeypatch):
    composition = importlib.import_module("functions_orchestration_composition")
    calls = _failing_search(harness, monkeypatch)
    harness.create(
        [_search_step(), _mixed_compose(inputs={
            "findings": {"binding": input_binding("search", "prepared"), "allow_partial": False, "optional": True},
        })],
        replies=["George Washington served from 1789 to 1797. (Web search was unavailable.)"],
        final_response=input_binding("prepare"),
    )
    plan = harness.read()["plan"]
    assert next(step for step in plan["steps"] if step["step_id"] == "search")["optional"] is True

    progress = []
    harness.prepare().execute(emit=progress.append)
    frames = decoded_frames(progress)
    saved = harness.read()
    payload = _compose_payload(harness)
    policy = _compose_messages(harness)[0]["content"]
    retry_events = [
        frame for frame in frames
        if frame.get("step_id") == "search" and "Retrying after a temporary service error." in frame.get("summary", "")
    ]

    assert calls == ["search", "search"]
    assert retry_events
    assert saved["status"] == "completed", saved.get("failure")
    assert payload["unavailable_inputs"] == [{
        "name": "findings",
        "reason": "The service used by this step reported an error before returning results.",
    }]
    assert "findings" not in payload["inputs"]
    assert composition.MISSING_INPUT_POLICY in policy
    assert composition.KNOWLEDGE_POLICIES["sources_and_general_knowledge"] in policy
    steps = _saved_steps(harness)
    assert steps["search"]["status"] == "failed"
    assert steps["search"]["failure"]["code"] == "provider_failed"
    assert steps["prepare"]["status"] == "completed"


def test_configuration_failures_are_not_retried(harness, monkeypatch):
    calls = _failing_search(harness, monkeypatch, failure_code="provider_not_configured")
    harness.create(
        [_search_step(), _mixed_compose(inputs={
            "findings": {"binding": input_binding("search", "prepared"), "allow_partial": False, "optional": True},
        })],
        replies=["Answered from general knowledge."], final_response=input_binding("prepare"),
    )

    harness.prepare().execute()

    assert calls == ["search"]
    assert harness.read()["status"] == "completed"


def test_a_required_input_still_fails_closed(harness, monkeypatch):
    _failing_search(harness, monkeypatch)
    harness.create(
        [_search_step(), _mixed_compose(inputs={
            "findings": {"binding": input_binding("search", "prepared"), "allow_partial": False},
        })],
        replies=[], final_response=input_binding("prepare"),
    )

    harness.prepare().execute()
    saved = harness.read()

    assert saved["status"] == "failed"
    assert harness.model_calls == []
    assert _saved_steps(harness)["prepare"]["status"] == "skipped"


def test_optional_inputs_require_general_knowledge_and_composition(harness):
    schema = harness.schema
    optional = {"binding": input_binding("search", "prepared"), "allow_partial": False, "optional": True}
    with pytest.raises(schema.PlanValidationError):
        harness.create([_search_step(), _mixed_compose(inputs={"findings": optional}, basis="sources")])
    with pytest.raises(schema.PlanValidationError):
        harness.create([_search_step(), _mixed_compose(inputs={"findings": optional}, basis="")])
    with pytest.raises(schema.PlanValidationError):
        harness.create([
            compose_step(),
            {**render_step("report", "md"), "inputs": {"source": {**optional, "binding": input_binding("prepare")}}},
        ])


def test_a_producer_the_final_response_needs_stays_required(harness):
    harness.create(
        [compose_step("draft"), _mixed_compose(inputs={
            "draft": {"binding": input_binding("draft"), "allow_partial": False, "optional": True},
        })],
        final_response=input_binding("draft"),
    )
    steps = {step["step_id"]: step for step in harness.read()["plan"]["steps"]}
    assert steps["draft"]["optional"] is False


# ------------------------------------------------------------------------------------------
# Visuals named by the planner
# ------------------------------------------------------------------------------------------

def test_compose_visuals_come_from_planner_flags_not_keywords(harness):
    visuals = importlib.import_module("functions_orchestration_visuals")
    harness.settings["enable_image_generation"] = True
    harness.create(
        [_mixed_compose(visuals=["diagram", "image_proposal"], basis="general_knowledge")],
        replies=["A report with a diagram."], final_response=input_binding("prepare"),
    )
    harness.prepare().execute()
    system = "\n".join(message["content"] for message in _compose_messages(harness) if message["role"] == "system")

    assert visuals.VISUAL_OUTPUT_POLICY_MARKER in system
    assert "mermaid" in system.lower()
    assert "[OPT_IN_IMAGE_GENERATION_PROPOSAL_GUIDANCE]" in system


def test_compose_without_visual_flags_or_markdown_gets_no_visual_guidance(harness):
    visuals = importlib.import_module("functions_orchestration_visuals")
    harness.settings["enable_image_generation"] = True
    records = compose_step(outputs=[{"name": "rows", "kind": "records-v1", "columns": [
        {"name": "State", "value_type": "string", "nullable": False},
        {"name": "Capital", "value_type": "string", "nullable": False},
    ]}])
    records["arguments"].update(knowledge_basis="general_knowledge", visuals=["chart"])
    table = render_step("capitals", "csv", output="rows")
    table["arguments"]["options"] = {"columns": ["State", "Capital"]}
    harness.create(
        [records, table],
        replies=[json.dumps({"rows": [{"State": "Alabama", "Capital": "Montgomery"}]})],
    )
    harness.prepare().execute()
    system = "\n".join(message["content"] for message in _compose_messages(harness) if message["role"] == "system")

    assert visuals.VISUAL_OUTPUT_POLICY_MARKER not in system
    assert harness.read()["status"] == "completed"
    assert harness.blobs.file_uploads == 1


def test_charts_drawn_by_gathering_are_placed_in_the_answer(harness):
    chart = "```simplechart\n" + json.dumps({"chartId": "voltage", "kind": "line", "title": "Voltage", "data": {
        "labels": ["t1", "t2"], "datasets": [{"label": "V", "data": [1, 2]}],
    }}) + "\n```"
    gathered = compose_step("gathered", outputs=[{"name": "prepared", "kind": "structured-v1"}])
    harness.create(
        [gathered, _mixed_compose(inputs={
            "gathered": {"binding": input_binding("gathered", "prepared"), "allow_partial": False},
        }, visuals=["chart"], basis="sources")],
        replies=[
            json.dumps({"prepared": {"citations": [{"function_result": {
                "chart_markdown": chart, "chart_payload": {"chartId": "voltage"},
            }}]}}),
            "Voltage rose steadily.\n\n[[chart:voltage]]\n\nEnd of report.",
        ],
        final_response=input_binding("prepare"),
    )

    harness.prepare().execute()
    saved = harness.read()
    payload = _compose_payload(harness)

    assert "[[chart:voltage]]" in payload["existing_charts"]
    assert saved["status"] == "completed"
    assert chart in saved["message"] and "[[chart:voltage]]" not in saved["message"]


def test_dependency_gather_steps_read_structured_visual_flags():
    adapters = importlib.import_module("functions_orchestration_adapters")
    context = SimpleNamespace(plan_contract_version=2, resolved_message="Plot voltage", user_message="Plot voltage")
    step = {"arguments": {"action_ref": "a", "task": "Read voltage", "visuals": ["chart"]}}
    visuals = adapters._step_visuals(context, {}, "Read voltage", step=step)
    assert visuals["chart"] is True and visuals["explicit_chart"] is True
    assert adapters._step_visuals(context, {}, "chart the voltage", step={"arguments": {}}) == {}


# ------------------------------------------------------------------------------------------
# Planner descriptor
# ------------------------------------------------------------------------------------------

def test_planner_descriptor_exposes_only_display_facts():
    planner = importlib.import_module("functions_orchestration_planner")
    model = SimpleNamespace(
        model_metadata={"displayName": "GPT 5.4", "endpoint": "https://private.invalid", "api_key": "secret"},
        deployment="gpt-54-deployment", source="request",
        reasoning_resolution={"effective_effort": "low"},
    )
    assert planner.describe_planner_model(model, "gpt-54-deployment") == {
        "label": "GPT 5.4", "source": "selected", "reasoning_effort": "low",
    }
    override = SimpleNamespace(model_metadata={}, deployment="planner-mini", source="planner_override")
    assert planner.describe_planner_model(override, "planner-mini") == {
        "label": "planner-mini", "source": "planner_setting",
    }
    assert planner.describe_planner_model(None, "fallback") == {"label": "fallback", "source": "default"}


# ------------------------------------------------------------------------------------------
# Web search failure classification and citation links
# ------------------------------------------------------------------------------------------

class _StatusError(Exception):
    def __init__(self, status):
        super().__init__("provider body that must not be kept")
        self.status_code = status


class APITimeoutError(Exception):
    pass


def test_web_search_failures_are_classified_without_provider_text():
    results = importlib.import_module("functions_web_search_results")
    try:
        try:
            raise _StatusError(429)
        except _StatusError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        described = results.describe_web_search_exception(outer)
    assert described == {
        "error_type": "RuntimeError", "provider_status": 429,
        "provider_timeout": False, "provider_connection": False,
    }
    assert results.describe_web_search_exception(APITimeoutError())["provider_timeout"] is True
    assert results.describe_web_search_exception(ConnectionResetError())["provider_connection"] is True

    adapters = importlib.import_module("functions_orchestration_adapters")
    schema = importlib.import_module("functions_orchestration_schema")
    cases = [
        ({"status": "agent_not_configured"}, "provider_not_configured", False),
        ({"status": "unexpected_error", "provider_status": 429}, "provider_http_error", True),
        ({"status": "unexpected_error", "provider_status": 400}, "provider_http_error", False),
        ({"status": "unexpected_error", "provider_timeout": True}, "provider_timeout", True),
        ({"status": "unexpected_error", "provider_connection": True}, "connection_failed", True),
        ({"status": "foundry_invocation_error"}, "provider_failed", True),
        (None, "provider_failed", True),
    ]
    for run, code, transient in cases:
        failure = adapters._web_search_failure(run)
        assert failure["code"] == code
        assert schema.failure_is_transient(failure) is transient
    assert adapters._web_search_failure({"provider_status": 503})["message"] == (
        "The service used by this step returned HTTP 503."
    )
    assert schema.failure_is_transient(schema.build_failure("context_unavailable")) is False


def test_foundry_citation_placeholders_become_numbered_links():
    results = importlib.import_module("functions_web_search_results")
    text = (
        "Washington served 1789-1797 【3:1†source】. Adams followed 【3:2†source】【3:1†source】. "
        "Unmapped 【9:9†source】 text."
    )
    citations = [
        {"url": "https://www.whitehouse.gov/about/presidents/george-washington/", "title": "Washington",
         "quote": "【3:1†source】"},
        {"url": "https://www.whitehouse.gov/about/presidents/john-adams/", "title": "Adams",
         "quote": "【3:2†source】"},
        # xss-check: ignore - hostile test data proving a non-http URL never becomes a link.
        {"url": "javascript:alert(1)", "title": "Bad", "quote": "【3:3†source】"},
    ]
    linked, sources = results.link_foundry_citation_markers(text, citations)

    assert "†" not in linked and "【" not in linked
    assert "[1](https://www.whitehouse.gov/about/presidents/george-washington/)" in linked
    assert "[2](https://www.whitehouse.gov/about/presidents/john-adams/)" in linked
    assert [source["number"] for source in sources] == [1, 2]
    formatted = results.format_linked_search_results("Web search results", text, citations)
    assert formatted.startswith("Web search results:\n")
    assert "[2] Adams - https://www.whitehouse.gov/about/presidents/john-adams/" in formatted
    assert results.format_linked_search_results("Results", "No citations here.", []) == (
        "Results:\nNo citations here."
    )


def test_legacy_executor_retries_a_transient_read_only_failure_once(monkeypatch):
    executor = importlib.import_module("functions_orchestration_executor")
    schema = importlib.import_module("functions_orchestration_schema")
    monkeypatch.setattr(executor, "_TRANSIENT_RETRY_DELAY_SECONDS", 0)
    step = {"step_id": "search", "capability_id": "web_search"}
    failed = schema.build_step_result(
        status=schema.STEP_STATUS_FAILED, failure=schema.build_failure("provider_timeout"),
    )
    assert executor._should_retry_transient(step, failed, lambda: False) is True
    assert executor._should_retry_transient(step, failed, lambda: True) is False
    assert executor._should_retry_transient({"capability_id": "action_invoke"}, failed, lambda: False) is False
    denied = schema.build_step_result(status=schema.STEP_STATUS_FAILED, failure=schema.build_failure("context_unavailable"))
    assert executor._should_retry_transient(step, denied, lambda: False) is False
    assert executor._pause_before_retry(lambda: False, delay=0) is True
    assert executor._pause_before_retry(lambda: True, delay=0) is False


def test_new_plans_use_the_dependency_contract_under_auto_routing():
    route_source = (
        importlib.util.find_spec("route_backend_orchestration").origin
    )
    with open(route_source, encoding="utf-8") as handle:
        source = handle.read()
    body = source.split("def _new_plan_contract_version(settings, seeds):", 1)[1].split("\ndef ", 1)[0]
    assert "model_routing" not in body
    assert "get_new_plan_contract_version(" in body


def test_retry_flag_marks_only_read_only_gather_capabilities(harness):
    registry = importlib.import_module("functions_orchestration_registry")
    flagged = {capability["id"] for capability in registry.CAPABILITY_REGISTRY if capability.get("retry_on_transient")}
    assert flagged == {"document_search", "web_search", "url_fetch", "deep_research"}
    dependency = {
        capability["id"]: capability for capability in registry.capabilities_for_contract(2)
    }
    compose = dependency["compose"]
    assert compose["optional_inputs_supported"] is True
    assert compose["inputs"]["properties"]["knowledge_basis"]["enum"] == list(registry.KNOWLEDGE_BASES)
    assert dependency["action_invoke"]["inputs"]["properties"]["visuals"]["items"]["enum"] == ["chart"]
    assert "retry_on_transient" not in dependency["action_invoke"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
