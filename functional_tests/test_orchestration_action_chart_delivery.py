#!/usr/bin/env python3
# test_orchestration_action_chart_delivery.py
"""
Functional test for orchestration charts that an action draws reaching the user.
Version: 0.261.291
Implemented in: 0.261.291

This test ensures that a request such as "Plot BatteryVoltage1 over the last 15 minutes"
never ends with a chart that was drawn and then thrown away:

- planning requires every gather step's results to be read by a step that ends in the
  answer, a file or a generated image (workflow_run is the only exception), and every
  planned chart or diagram to reach the answer or a file; a plan that breaks either rule
  gets the planner's single correction round;
- a chart an action drew is shown even when no answer step placed it, the way a generated
  image is, and the answer step is sent the chart's placement token instead of its data;
- a chart the user asked for that the answer does not show is reported as not delivered,
  the run is partial, and a retry runs the step that draws it again after confirmation;
- a saved plan that gathered without answering says so instead of "content is prepared";
- a large gathered value is saved in a few pages instead of one page per JSON token.

Production planner, schema, executor, execution, recovery and result services run in the
offline harness. Only the action's tool calls and the model are doubled.
"""

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.versioning import assert_app_version_at_least


IMPLEMENTED_IN = "0.261.291"
ACTION = {
    "action_ref": "action:v1:global:simulation", "id": "simulation", "name": "simulation",
    "display_name": "Simulation", "scope_label": "Global", "type": "yamcs",
    "description": "Reads archived spacecraft telemetry.",
}
AVAILABLE = ["compose", "render_file", "web_search", "document_search", "action_invoke"]
CHART_REQUEST = "Plot BatteryVoltage1 over the last 15 minutes, provide high granularity"
CHART_DESCRIPTION = "A high-granularity time-series plot of BatteryVoltage1 for the last 15 minutes."
ANSWER_TEXT = "BatteryVoltage1 stayed between 27.1 V and 27.4 V.\n\n[[chart:battery]]"


def _chart_markdown():
    charts = importlib.import_module("functions_chart_operations")
    return charts.build_inline_chart_markdown({
        "version": 1, "kind": "line", "chartType": "line", "chartId": "battery",
        "title": "BatteryVoltage1", "subtitle": "All points shown.",
        "data": {
            "labels": ["17:29:30", "17:29:31", "17:29:32"],
            "datasets": [{"label": "BatteryVoltage1", "data": [27.1, 27.4, 27.2]}],
        },
    })


def _citations(with_chart=True):
    telemetry = {
        "tool_name": "Simulation", "plugin_name": "YamcsPlugin", "function_name": "list_parameter_history",
        "function_result": {"rows": [
            {"generation_time": "2026-10-07T17:29:30Z", "eng_value": 27.1},
            {"generation_time": "2026-10-07T17:29:31Z", "eng_value": 27.4},
            {"generation_time": "2026-10-07T17:29:32Z", "eng_value": 27.2},
        ]},
    }
    chart = {
        "tool_name": "Chart", "plugin_name": "ChartPlugin", "function_name": "chart_retrieved_rows",
        "function_result": {"success": True, "chart_payload": {"chartId": "battery"}, "chart_markdown": _chart_markdown()},
    }
    return [telemetry, chart] if with_chart else [telemetry]


def _deliverable(identifier="battery_chart", kind="chart", description=CHART_DESCRIPTION):
    return {"id": identifier, "kind": kind, "requested": "explicit", "description": description, "status": "planned"}


def _action_step(*, delivers=("battery_chart",)):
    return {
        "step_id": "retrieve", "capability_id": "action_invoke", "title": "Retrieve and plot BatteryVoltage1 telemetry",
        "arguments": {
            "action_ref": ACTION["action_ref"],
            "task": "Retrieve archived BatteryVoltage1 samples for the last 15 minutes at native resolution.",
            "visuals": ["chart"],
        },
        **({"delivers": list(delivers)} if delivers else {}),
    }


def _answer_step():
    step = compose_step("answer", inputs={
        "telemetry": {"binding": input_binding("retrieve", "prepared"), "allow_partial": False},
    })
    step["arguments"]["knowledge_basis"] = "sources"
    return step


def _incident_plan():
    """The plan saved for the reported run: one gather step and no step that writes the answer."""
    return {"deliverables": [_deliverable()], "steps": [_action_step()]}


def _answered_plan():
    return {
        "deliverables": [_deliverable()], "steps": [_action_step(), _answer_step()],
        "final_response": input_binding("answer"),
    }


def _availability(harness):
    deliverables = importlib.import_module("functions_orchestration_deliverables")
    return deliverables.build_deliverable_availability(
        harness.settings, capabilities=[{"id": capability_id} for capability_id in AVAILABLE],
    )


def _normalize(harness, raw, *, strict=False):
    return harness.schema.normalize_plan(
        {"run_id": "run-1", "plan_id": "plan-1", "turn_id": "turn-1", **deepcopy(raw)},
        "conversation-1", "owner", settings=harness.settings, contract_version=2,
        available_capability_ids=AVAILABLE, actions=[ACTION],
        deliverable_availability=_availability(harness) if strict else None,
        composition_profiles=harness.service_bindings.composition_profiles(),
    )


def _store(harness, plan, *, replies=()):
    """Save a validated plan as run-1, exactly as the harness saves its own fixtures."""
    run_store = importlib.import_module("functions_orchestration_runs")
    context = importlib.import_module("functions_orchestration_context")
    memory = importlib.import_module("functions_orchestration_memory")
    normalized = context.normalize_history_message(harness.turn)
    turn_context = {
        "turn_id": "turn-1", "user_message": harness.turn["content"],
        "user_message_id": harness.turn["id"], "user_message_fingerprint": normalized["fingerprint"],
        "resolved_message": harness.turn["content"], "seeds": {}, "original_seeds": {},
        "answered_questions": [], "planning_token_usage": {},
        "conversation_context": context.build_conversation_snapshot([], harness.settings),
        "memory_audience": memory.validate_memory_audience(harness.conversation, "owner"),
        "memory_scope": None,
    }
    harness.replies = list(replies)
    return run_store.create_orchestration_run(plan, "owner", "conversation-1", turn_index=1, turn_context=turn_context)


def _enable_action(harness, monkeypatch, *, with_chart=True):
    """The Simulation action returns its rows, and a chart unless chart creation failed.

    Only the tool calls are doubled: the executor, retention, result service and publication
    are the production ones. The retained value has the shape run_action_invoke returns.
    """
    executor = importlib.import_module("functions_orchestration_executor")
    schema = importlib.import_module("functions_orchestration_schema")
    results = importlib.import_module("functions_orchestration_results")
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    original = executor._dependency_adapter
    calls = []

    def action(step, context, **kwargs):
        calls.append(step["step_id"])
        findings = "Retrieved 3 BatteryVoltage1 samples." + (
            '\n\nCharts created from the retrieved results: "BatteryVoltage1".' if with_chart
            else "\n\nThe requested chart could not be created from the retrieved results."
        )
        return schema.build_step_result(
            status=schema.STEP_STATUS_COMPLETED,
            summary="Used Simulation (3 function calls) and created 1 chart." if with_chart
            else "Used Simulation (3 function calls).",
            notes=[f'Action "Simulation" findings:\n{findings}'], citations=_citations(with_chart),
        )

    def retain(step, context, result, *, source_manifest):
        complete = contracts.Completeness(
            "complete", 1, 1, contracts.Coverage(1, 1, "work_units"), "valid", ("test_action",), (),
        )
        prepared = {
            "version": "orchestration-gathered-content-v1", "capability_id": step["capability_id"],
            "content_scope": "reported_external_content", "evidence": [],
            "notes": result["notes"], "citations": result["citations"], "limitations": [],
        }
        return context.result_service.persist_task_result(
            producer=context.result_producer(step), role="gather", status="complete",
            outputs=[results.NamedOutput("prepared", "structured-v1", prepared, complete)],
            sources=[], origin="generated", guard_token=context.result_guard_token_for_step(step["step_id"]),
            input_fingerprint=context.result_input_fingerprint_for_step(step["step_id"]),
        )

    monkeypatch.setattr(
        executor, "_dependency_adapter",
        lambda capability_id: action if capability_id == "action_invoke" else original(capability_id),
    )
    monkeypatch.setattr(executor, "retain_gather_result", retain)
    monkeypatch.setattr(harness.execution, "resolve_action_catalog", lambda *args, **kwargs: [deepcopy(ACTION)])
    monkeypatch.setattr(harness.execution, "resolve_agent_catalog", lambda *args, **kwargs: [])
    harness.settings.update({"enable_semantic_kernel": True, "enable_chat_orchestration_actions": True})
    return calls


def _compose_payload(harness):
    calls = [call for call in harness.model_calls if call["messages"][0]["content"].startswith("Prepare only")]
    assert len(calls) == 1
    return json.loads(calls[0]["messages"][-1]["content"])


def _orchestration_metadata(harness):
    (message,) = harness.assistant_messages()
    return message, message["metadata"]["orchestration"]


def test_version_is_at_least_the_fix():
    assert_app_version_at_least(IMPLEMENTED_IN)


# ------------------------------------------------------------------------------------------
# Planning: gathered results are always read, and a chart always has somewhere to appear
# ------------------------------------------------------------------------------------------

def test_the_planner_is_told_that_gathered_results_and_charts_must_reach_the_user(harness):
    prompt = " ".join(harness.planner.build_planner_messages({})[0]["content"].split())
    assert "Every gather step's results must be used" in prompt
    # A request that cannot start workflows is never told about them (see the run capability tests).
    assert "workflow_run" not in prompt
    run_rules = " ".join(harness.planner.WORKFLOW_RUN_INSTRUCTIONS.split())
    assert "it is the only gather step that no step reads" in run_rules
    assert "action_invoke can deliver a chart of the rows it retrieves." not in prompt
    assert (
        "the compose step that binds its output and is the final_response places that chart in the answer"
    ) in prompt
    assert "A chart or diagram appears only in the final_response answer or in content a render_file step saves" in prompt
    recipe = next(
        recipe["steps"] for recipe in _availability(harness)["recipes"]
        if recipe["for"] == "Chart of data an action retrieves"
    )
    assert 'bind its "prepared" output to the compose step that is the final_response' in recipe


def test_planning_refuses_the_reported_gather_only_chart_plan_and_accepts_its_correction(harness):
    with pytest.raises(harness.schema.PlanValidationError) as refused:
        _normalize(harness, _incident_plan(), strict=True)
    assert refused.value.code == "deliverables_invalid"
    assert refused.value.rule == "visual_not_published"
    assert "would never be shown" in str(refused.value)
    assert 'bind its "prepared" output as a named input of that compose step' in str(refused.value)

    plan = _normalize(harness, _answered_plan(), strict=True)
    assert [step["step_id"] for step in plan["steps"]] == ["retrieve", "answer"]
    assert plan["final_response"]["step_id"] == "answer"
    assert plan["steps"][0]["delivers"] == ["battery_chart"]
    # A saved plan is revalidated without the planning rule, so plans saved before it still load.
    saved = _normalize(harness, _incident_plan())
    assert "final_response" not in saved and saved["steps"][0]["delivers"] == ["battery_chart"]


def _compiled(step_id, capability_id, role, *, inputs=None, outputs=None, delivers=None, arguments=None):
    return {
        "step_id": step_id, "capability_id": capability_id, "role": role, "enabled": True,
        "arguments": arguments or {}, "inputs": inputs or {},
        "outputs": [{"name": "answer", "kind": "markdown-v1"}] if outputs is None else outputs,
        **({"delivers": list(delivers)} if delivers else {}),
    }


def _bound(step_id, output_name):
    return {"binding": input_binding(step_id, output_name), "allow_partial": False}


def _strict_compile(harness, deliverables, steps, final_step=None):
    module = importlib.import_module("functions_orchestration_deliverables")
    return module.compile_deliverables(
        deliverables, steps, final_response=input_binding(final_step) if final_step else None,
        availability=_availability(harness),
    )


def test_every_gather_step_must_feed_the_answer_a_file_or_an_image(harness):
    module = importlib.import_module("functions_orchestration_deliverables")
    prepared = [{"name": "prepared", "kind": "structured-v1"}]
    search = _compiled("search", "web_search", "gather", outputs=prepared)

    with pytest.raises(module.DeliverableError) as unread:
        _strict_compile(harness, None, [deepcopy(search)])
    assert unread.value.rule == "gather_not_used"
    assert 'Gather step "search" collects results that no later step reads' in unread.value.message

    # A structured result nobody sees does not count as reading the gathered results.
    hidden = _compiled(
        "notes", "compose", "reason", inputs={"findings": _bound("search", "prepared")},
        outputs=[{"name": "notes", "kind": "structured-v1"}],
    )
    with pytest.raises(module.DeliverableError) as structured:
        _strict_compile(harness, None, [deepcopy(search), hidden])
    assert structured.value.rule == "gather_not_used"

    answer = _compiled("answer", "compose", "reason", inputs={"findings": _bound("search", "prepared")})
    assert _strict_compile(harness, None, [deepcopy(search), answer], "answer")[0]["implicit"] is True

    # Gathered results may also end in a file, through the step that prepares it.
    content = _compiled("content", "compose", "reason", inputs={"findings": _bound("search", "prepared")})
    render = _compiled(
        "file", "render_file", "render", outputs=[], delivers=["report"],
        inputs={"source": _bound("content", "answer")},
        arguments={"file_name": "report.docx", "output_format": "docx", "profile": "prepared_report_v1"},
    )
    report = {**_deliverable("report", "file", "The report"), "format": "docx"}
    assert _strict_compile(harness, [report], [deepcopy(search), content, render])[0]["id"] == "report"

    # Starting a saved workflow is the one gather step nothing reads; the server writes its reply.
    started = _compiled("start", "workflow_run", "gather", outputs=[{"name": "run", "kind": "structured-v1"}])
    assert _strict_compile(harness, None, [started])[0]["implicit"] is True

    # Saved plans are compiled without availability and keep loading unchanged.
    assert module.compile_deliverables(None, [deepcopy(search)])[0]["implicit"] is True


def test_a_chart_or_diagram_must_reach_the_answer_or_a_file(harness):
    module = importlib.import_module("functions_orchestration_deliverables")
    diagram = _deliverable("flow", "diagram", "A diagram of the process")
    drafted = _compiled("draft", "compose", "reason", delivers=["flow"])
    with pytest.raises(module.DeliverableError) as unseen:
        _strict_compile(harness, [diagram], [drafted])
    assert unseen.value.rule == "visual_not_published"

    shown = _compiled("draft", "compose", "reason", delivers=["flow"])
    assert _strict_compile(harness, [diagram], [shown], "draft")[0]["id"] == "flow"

    # A diagram written into a file's content keeps the file plan valid.
    content = _compiled("content", "compose", "reason", delivers=["flow"])
    render = _compiled(
        "file", "render_file", "render", outputs=[], delivers=["report"],
        inputs={"source": _bound("content", "answer")},
        arguments={"file_name": "report.docx", "output_format": "docx", "profile": "prepared_report_v1"},
    )
    report = {**_deliverable("report", "file", "The report"), "format": "docx"}
    assert {item["id"] for item in _strict_compile(harness, [diagram, report], [content, render])} == {"flow", "report"}


def test_a_gather_only_plan_gets_one_correction_round(harness):
    harness.settings["enable_web_search"] = True
    gather_only = {
        "kind": "plan", "intent": {"summary": "Find the current Seattle weather."}, "assumptions": [],
        "steps": [{"step_id": "search", "capability_id": "web_search", "arguments": {
            "query": "Current weather in Seattle, Washington",
        }}],
    }
    corrected = deepcopy(gather_only)
    corrected["steps"].append(_compiled_answer_step())
    corrected["final_response"] = input_binding("answer")

    harness.replies = [json.dumps(gather_only), json.dumps(corrected)]
    kind, plan = harness.planner.plan_request(
        "What is the weather in Seattle?", {}, "conversation-1", "owner", settings=harness.settings, seeds={},
        contract_version=2, request_context=harness.services().capability_request_bindings(),
    )
    assert kind == "plan" and len(harness.model_calls) == 2
    repair = harness.model_calls[1]["messages"][-1]["content"]
    assert repair.startswith("The server rejected that plan:")
    assert 'Gather step "search" collects results that no later step reads' in repair
    assert [step["step_id"] for step in plan["steps"]] == ["search", "answer"]

    harness.model_calls.clear()
    harness.replies = [json.dumps(gather_only), json.dumps(gather_only)]
    with pytest.raises(harness.planner.PlannerError) as failure:
        harness.planner.plan_request(
            "What is the weather in Seattle?", {}, "conversation-1", "owner", settings=harness.settings,
            seeds={}, contract_version=2, request_context=harness.services().capability_request_bindings(),
        )
    assert failure.value.message == harness.planner.DELIVERABLES_FAILURE_MESSAGE


def _compiled_answer_step():
    step = compose_step("answer", inputs={
        "weather": {"binding": input_binding("search", "prepared"), "allow_partial": False},
    })
    step["arguments"]["knowledge_basis"] = "sources"
    return step


# ------------------------------------------------------------------------------------------
# Execution: the chart the action drew is shown, once
# ------------------------------------------------------------------------------------------

def test_the_reported_plan_now_shows_the_chart_the_action_drew(harness, monkeypatch):
    calls = _enable_action(harness, monkeypatch)
    _store(harness, _normalize(harness, _incident_plan()))

    harness.prepare().execute()
    saved = harness.read()
    message, metadata = _orchestration_metadata(harness)
    answer = message["content"]

    assert calls == ["retrieve"]
    assert saved["status"] == "completed" and saved["outcome"] == "completed", saved.get("failure")
    assert answer.count("```simplechart") == 1 and '"chartId":"battery"' in answer
    assert "The requested content is prepared" not in answer and "Delivery notes" not in answer
    assert saved["deliverable_states"] == [{"id": "battery_chart", "state": "delivered"}]
    assert saved["redraw_step_ids"] == []
    assert metadata["deliverable_states"] == [{"id": "battery_chart", "state": "delivered"}]


def test_the_answer_step_places_the_chart_from_its_token_without_rereading_its_data(harness, monkeypatch):
    _enable_action(harness, monkeypatch)
    _store(harness, _normalize(harness, _answered_plan(), strict=True), replies=[ANSWER_TEXT])

    harness.prepare().execute()
    saved = harness.read()
    message, _ = _orchestration_metadata(harness)
    answer = message["content"]
    payload = _compose_payload(harness)
    citations = payload["inputs"]["telemetry"]["value"]["citations"]

    assert saved["status"] == "completed", saved.get("failure")
    assert answer.startswith("BatteryVoltage1 stayed between 27.1 V and 27.4 V.")
    assert answer.count("```simplechart") == 1 and "[[chart:" not in answer
    # The model is sent the token; the server places the chart from the exact rows.
    assert citations[1]["function_result"] == {"success": True, "chart_markdown": "[[chart:battery]]"}
    assert citations[0]["function_result"]["rows"][1]["eng_value"] == 27.4
    assert "[[chart:battery]] BatteryVoltage1" in payload["existing_charts"]
    assert "```simplechart" not in json.dumps(payload)
    assert saved["deliverable_states"] == [{"id": "battery_chart", "state": "delivered"}]


def test_a_chart_that_could_not_be_drawn_is_not_delivered_and_a_retry_draws_it_again(harness, monkeypatch):
    _enable_action(harness, monkeypatch, with_chart=False)
    _store(
        harness, _normalize(harness, _answered_plan(), strict=True),
        replies=["BatteryVoltage1 stayed between 27.1 V and 27.4 V."],
    )

    harness.prepare().execute()
    saved = harness.read()
    message, metadata = _orchestration_metadata(harness)
    answer = message["content"]
    recovery = harness.recovery.public_execution_fields(saved)["recovery"]

    assert saved["status"] == "failed" and saved["outcome"] == "partial"
    assert saved["failure"]["code"] == "visual_not_delivered"
    assert f"- Not delivered: {CHART_DESCRIPTION} The chart could not be created from the retrieved data." in answer
    assert "The request was only partially completed." in answer
    state = {
        "id": "battery_chart", "state": "not_delivered",
        "message": "The chart could not be created from the retrieved data.",
    }
    assert saved["deliverable_states"] == [state] and metadata["deliverable_states"] == [state]
    assert saved["redraw_step_ids"] == ["retrieve"]
    # A retry draws the chart again, and writes the answer again with it. Running the action
    # again repeats its calls, so the retry asks for confirmation first.
    assert recovery["eligible"] is True, recovery
    assert set(recovery["retry_step_ids"]) == {"retrieve", "answer"} and recovery["reused_step_ids"] == []
    assert recovery["requires_confirmation"] is True


def test_a_saved_plan_that_gathered_without_answering_says_so(harness, monkeypatch):
    _enable_action(harness, monkeypatch)
    plan = {"steps": [_action_step(delivers=())]}
    plan["steps"][0]["arguments"].pop("visuals")
    _store(harness, _normalize(harness, plan))

    harness.prepare().execute()
    message, _ = _orchestration_metadata(harness)
    deliverables = importlib.import_module("functions_orchestration_deliverables")

    assert message["content"] == deliverables.UNREAD_GATHER_MESSAGE
    assert "The requested content is prepared" not in message["content"]


# ------------------------------------------------------------------------------------------
# Delivery state, notes and public fields
# ------------------------------------------------------------------------------------------

def _task(status="complete", output_status="complete", name="prepared"):
    reference = SimpleNamespace(output_name=name, completeness=SimpleNamespace(status=output_status))
    return SimpleNamespace(status=status, outputs=(reference,))


def test_gathered_charts_are_read_only_from_steps_asked_to_chart_and_shown_once():
    module = importlib.import_module("functions_orchestration_deliverables")
    plan = {"steps": [
        {"step_id": "retrieve", "capability_id": "action_invoke", "arguments": {"visuals": ["chart"]}},
        {"step_id": "lookup", "capability_id": "action_invoke", "arguments": {}},
        {"step_id": "off", "capability_id": "action_invoke", "enabled": False, "arguments": {"visuals": ["chart"]}},
    ]}
    reads = []

    def read(reference):
        reads.append(reference.output_name)
        return {"citations": _citations()}

    tasks = {"retrieve": _task(), "lookup": _task(), "off": _task()}
    charts = module.gathered_charts(plan, tasks, read)
    assert list(charts) == ["retrieve"] and reads == ["prepared"]
    assert charts["retrieve"][0]["chart_id"] == "battery"
    assert module.gathered_charts(plan, {"retrieve": _task(status="failed")}, read) == {}

    shown = module.show_gathered_charts("", charts)
    assert shown.count("```simplechart") == 1
    assert module.show_gathered_charts(shown, charts) == shown
    assert module.show_gathered_charts("Answer.", charts).startswith("Answer.\n\n```simplechart")
    assert module.show_gathered_charts("Answer.", {}) == "Answer."


def test_visual_delivery_reports_charts_and_diagrams_meant_for_the_answer():
    module = importlib.import_module("functions_orchestration_deliverables")
    chart = _deliverable()
    diagram = _deliverable("flow", "diagram", "A diagram of the telemetry path")
    suggested = {**_deliverable("extra"), "requested": "suggested"}
    plan = {
        "deliverables": [chart, diagram, suggested],
        "final_response": input_binding("answer"),
        "steps": [
            {**_action_step(), "role": "gather", "inputs": {}},
            {**_answer_step(), "role": "reason", "delivers": ["flow"]},
        ],
    }
    statuses = {"retrieve": "completed", "answer": "completed"}
    charts = {"retrieve": [{"chart_id": "battery", "chart_markdown": _chart_markdown()}]}

    shown_answer = f"Text\n\n{_chart_markdown()}\n\n```mermaid\nflowchart LR\nA-->B\n```"
    states, redraw = module.visual_delivery(plan, statuses, shown_answer, charts)
    assert states == [{"id": "battery_chart", "state": "delivered"}, {"id": "flow", "state": "delivered"}]
    assert redraw == []

    states, redraw = module.visual_delivery(plan, statuses, "Text only.", {})
    assert states == [
        {"id": "battery_chart", "state": "not_delivered",
         "message": "The chart could not be created from the retrieved data."},
        {"id": "flow", "state": "not_delivered", "message": "The answer did not include it."},
    ]
    assert redraw == ["retrieve", "answer"]

    states, redraw = module.visual_delivery(plan, {"retrieve": "failed", "answer": "skipped"}, "", {})
    assert {state["message"] for state in states} == {"The step that makes it did not finish."}
    assert redraw == []

    notes = module.delivery_notes(plan, statuses, visual_states=module.visual_delivery(plan, statuses, "", {})[0])
    assert f"- Not delivered: {CHART_DESCRIPTION} The chart could not be created from the retrieved data." in notes
    assert "- Not delivered: A diagram of the telemetry path. The answer did not include it." in notes


def test_public_fields_carry_only_well_formed_deliverable_states(harness):
    record = {
        "id": "run-1", "plan": {"steps": []}, "status": "completed", "outcome": "completed",
        "deliverable_states": [
            {"id": "battery_chart", "state": "not_delivered", "message": "The answer did not include it.", "extra": 1},
            {"id": "flow", "state": "delivered"},
            {"id": "bad", "state": "shown"},
            "not a state",
            {"state": "delivered"},
        ],
    }
    fields = harness.recovery.public_execution_fields(record)
    assert fields["deliverable_states"] == [
        {"id": "battery_chart", "state": "not_delivered", "message": "The answer did not include it."},
        {"id": "flow", "state": "delivered"},
    ]
    assert "deliverable_states" not in harness.recovery.public_execution_fields({**record, "deliverable_states": []})


# ------------------------------------------------------------------------------------------
# Saving a large gathered value
# ------------------------------------------------------------------------------------------

def test_a_large_gathered_value_is_saved_in_a_few_pages_and_reads_back_exactly():
    results = importlib.import_module("functions_orchestration_results")
    collections = importlib.import_module("functions_workflow_collections")
    rows = [
        {"generation_time": f"2026-10-07T17:{minute:02d}:{second:02d}Z", "eng_value": 27 + (second % 7) / 10,
         "monitoring_result": "IN_LIMITS"}
        for minute in range(29, 45) for second in range(60)
    ]
    value = {"notes": ["Retrieved 960 samples."], "citations": [{"function_result": {"rows": rows}}]}
    encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    expected = "".join(encoder.iterencode(value))
    assert len(expected) > 64 * 1024

    def write(records):
        saved = []

        def save(section):
            saved.append(section)
            return {"sha256": f"{len(saved):064x}", "size_bytes": len(json.dumps(section))}

        writer = collections.RecordTreeWriter(
            {"step_id": "retrieve"}, "prepared", "records", save, max_result_bytes=64 * 1024 * 1024,
        )
        for text in records:
            writer.append({"data": text})
        writer.finish()
        data = "".join(
            item["data"] for section in saved if section["kind"] == "records" for item in section["value"]
        )
        return len(saved), data

    records = list(results._value_records(encoder.iterencode(value)))
    pages, data = write(records)
    assert data == expected
    assert all(len(text) <= 16384 for text in records) and len(records) == -(-len(expected) // 16384)
    # Before the fix every encoder token was its own record, one page per hundred tokens.
    token_pages, token_data = write(list(encoder.iterencode(value)))
    assert token_data == expected
    assert pages <= 3 < 100 < token_pages


def test_value_records_regroup_fragments_without_changing_the_text():
    results = importlib.import_module("functions_orchestration_results")
    fragments = ["a" * 5, "b" * 40000, "c", "", "d" * 16383, "e" * 16385]
    regrouped = list(results._value_records(iter(fragments), size=16384))
    assert "".join(regrouped) == "".join(fragments)
    assert all(len(text) == 16384 for text in regrouped[:-1]) and 0 < len(regrouped[-1]) <= 16384
    assert list(results._value_records(iter([]))) == []
    assert list(results._value_records(iter(["{", "}"]))) == ["{}"]


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
