# test_orchestration_compose_output_retry.py
"""Records guidance, JSON mode and the single corrective call for content preparation.

Version: 0.261.341
Implemented in: 0.261.141
Explicit chart/diagram omission correction implemented in: 0.261.341

A request for a CSV of the U.S. states and capitals planned correctly, then failed while
preparing content. The compose step was told to write "the finished file", so the model
returned CSV text, while its declared output was records-v1 rows. This test ensures that:

- file guidance matches the kind of value the saving step reads (rows and structured values
  are data, never file text), and the compose policy states each output's exact JSON shape;
- JSON preparation asks the endpoint for a JSON object, plain-text preparation never does, and
  an endpoint that refuses the option is asked again without it (any other refusal is not);
- a reply that breaks a declared rule gets exactly one corrective call naming that rule, and a
  second unusable reply, or a corrective call that would not fit, fails cleanly;
- compose logs carry application codes and hashed identifiers, never model content.

Uses the initialized headless harness (real bootstrap, planner, schema, executor, result
store and renderers) with the planning and answering models replaced by offline replies.
"""

import hashlib
import importlib
import json

import httpx
import pytest
from openai import BadRequestError

from test_orchestration_deliverables import (
    _csv_plan, _file_bytes, _files, _normalize, _plan_request, _saved_steps, _store,
)
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.versioning import assert_app_version_at_least


ROWS = [{"State": "Alabama", "Capital": "Montgomery"}, {"State": "Alaska", "Capital": "Juneau"}]
CSV_LINES = ["State,Capital", "Alabama,Montgomery", "Alaska,Juneau"]
SECRET_REPLY_TEXT = "PRIVATE_MODEL_REPLY_TEXT"
TIMELINE = """## Eating and drinking schedule

```mermaid
flowchart TB
    subgraph eating["Eating / fueling"]
        direction LR
        breakfast["Breakfast: 2 hours before"] --> snacks["Snacks: every 30 minutes"] --> meal["Meal: 1 hour after"]
    end
    subgraph drinking["Drinking / hydration"]
        direction LR
        before_fluids["Fluids: before the ride"] --> ride_fluids["Fluids: during the ride"] --> after_fluids["Fluids: after the ride"]
    end
```
"""
PRIOR_PLAN = {
    "id": "prior-nutrition-plan", "conversation_id": "conversation-1", "role": "assistant",
    "content": (
        "For your 40-mile gravel ride, eat breakfast 2 hours before departure, snacks every "
        "30 minutes during the ride, and a meal 1 hour after. Drink before, during, and after the ride."
    ),
    "timestamp": "2026-09-21T17:55:00+00:00",
}


def test_version_includes_the_compose_output_retry():
    assert_app_version_at_least("0.261.141")
    assert_app_version_at_least("0.261.341")


def _provider_error(*, param, code, message):
    detail = {"message": message, "type": "invalid_request_error", "param": param, "code": code}
    return BadRequestError(
        message,
        response=httpx.Response(400, request=httpx.Request("POST", "https://offline.invalid/chat/completions")),
        body={"error": detail},
    )


def _format_refused():
    return _provider_error(
        param="response_format", code="unsupported_parameter",
        message="'response_format' of type 'json_object' is not supported with this model.",
    )


def _compose_calls(harness):
    return [call for call in harness.model_calls if call["messages"][0]["content"].startswith("Prepare only")]


def _run_csv(harness, replies):
    kind, plan = _plan_request(harness, [_csv_plan()], message="create a csv of states and capitals")
    assert kind == "plan"
    _store(harness, plan, replies=replies)
    harness.prepare().execute()
    return harness.read()


def _capture(monkeypatch, module_name):
    module = importlib.import_module(module_name)
    appinsights = importlib.import_module("functions_appinsights")
    # A shared fixture elsewhere can leave this module cached from an import made while
    # functions_appinsights was stubbed. Bind the real helper so hashed identifiers are checked.
    if not getattr(appinsights, "__file__", None):
        raise AssertionError("The real functions_appinsights must be loaded.")
    events = []
    monkeypatch.setattr(module, "log_event", lambda message, **kwargs: events.append((message, kwargs)))
    monkeypatch.setattr(module, "workflow_log_context", appinsights.workflow_log_context)
    return events


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------
# Guidance and policy
# ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("kind", "expected", "absent"), [
    (
        "records-v1",
        'A later step saves output "content" as out.csv, a CSV file, from the rows you return. '
        'Return "content" as rows, not as file text: that step writes the file.',
        "Write its complete content as the finished file",
    ),
    (
        "structured-v1",
        'A later step saves output "content" as out.csv, a CSV file, from the value you return. '
        'Return "content" as the structured value its schema or profile describes, not as file text',
        "Write its complete content as the finished file",
    ),
    (
        "markdown-v1",
        'A later step saves output "content" as out.csv, a CSV file. Write its complete content as '
        "the finished file",
        "not as file text",
    ),
])
def test_file_guidance_matches_the_value_the_saving_step_reads(initialized_application, kind, expected, absent):
    deliverables = importlib.import_module("functions_orchestration_deliverables")
    step = {
        "outputs": [{"name": "content", "kind": kind}],
        "deliverable_context": [{
            "relation": "rendered_as", "id": "file", "kind": "file", "requested": "explicit",
            "description": "The file", "format": "csv", "output": "content", "file_name": "out.csv",
            "enabled": True,
        }],
    }

    guidance = "\n".join(deliverables.compose_deliverable_guidance(step, []))

    assert expected in guidance
    assert absent not in guidance
    assert "Never say files cannot be created." in guidance


def test_output_shapes_come_from_the_declared_columns(initialized_application):
    composition = importlib.import_module("functions_orchestration_composition")
    records = composition._output_shape({"name": "rows", "kind": "records-v1", "columns": [
        {"name": "State", "value_type": "string", "nullable": False},
        {"name": "Population", "value_type": "integer", "nullable": True},
        {"name": "Coastal", "value_type": "boolean", "nullable": False},
    ]})

    assert records.startswith('Output "rows" is a JSON array with one object per row, not CSV or table text.')
    assert 'exactly the keys "State" (string), "Population" (integer or null), "Coastal" (true or false).' in records
    shape = json.loads(records.partition("Shape: ")[2])
    assert list(shape) == ["rows"] and list(shape["rows"][0]) == ["State", "Population", "Coastal"]
    assert composition._output_shape({"name": "summary", "kind": "markdown-v1"}) == (
        'Output "summary" is one non-empty JSON string of Markdown.'
    )
    assert composition._output_shape({"name": "deck", "kind": "structured-v1", "profile": "p"}) == (
        'Output "deck" is the JSON value its declared schema or profile describes.'
    )


# ------------------------------------------------------------------------------------------
# JSON mode
# ------------------------------------------------------------------------------------------

def test_plain_text_preparation_never_requests_json_mode(harness):
    harness.create([compose_step()], replies=["# The approved answer"])

    harness.prepare().execute()

    calls = _compose_calls(harness)
    assert harness.read()["status"] == "completed"
    assert len(calls) == 1 and "response_format" not in calls[0]


def test_an_endpoint_refusing_json_mode_is_asked_again_without_it(harness, monkeypatch):
    events = _capture(monkeypatch, "functions_orchestration_execution")

    saved = _run_csv(harness, [_format_refused(), json.dumps({"rows": ROWS})])

    calls = _compose_calls(harness)
    assert saved["status"] == "completed", saved.get("failure")
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert calls[0]["messages"] == calls[1]["messages"]
    assert _file_bytes(harness, ".csv").decode("utf-8").splitlines() == CSV_LINES
    retries = [kwargs["extra"] for _message, kwargs in events if kwargs.get("extra", {}).get("reason") == "json_format_retry"]
    assert retries == [{"stage": "orchestration_compose", "reason": "json_format_retry", "error_type": "BadRequestError"}]


def test_any_other_refusal_is_not_resent_without_json_mode(harness):
    refused = _provider_error(
        param="messages", code="invalid_request_error",
        message="'messages' must contain the word 'json' in some form, to use 'response_format'.",
    )

    saved = _run_csv(harness, [refused])

    calls = _compose_calls(harness)
    assert saved["status"] == "failed"
    assert len(calls) == 1 and calls[0]["response_format"] == {"type": "json_object"}
    assert _files(harness, ".csv") == []


@pytest.mark.parametrize(("error", "expected"), [
    (_format_refused(), True),
    (_provider_error(
        param=None, code=None,
        message="'response_format' of type 'json_object' is not supported with this model.",
    ), True),
    (_provider_error(param="response_format.type", code="unsupported_value", message="Unsupported value."), True),
    (_provider_error(param="messages", code=None, message="'messages' must contain the word 'json'."), False),
    (_provider_error(param="reasoning_effort", code="unsupported_value", message="Unsupported value."), False),
    (_provider_error(param=None, code=None, message="The request is invalid."), False),
    (ValueError("response_format is not supported"), False),
])
def test_only_a_refused_response_format_is_recognized(initialized_application, error, expected):
    clients = importlib.import_module("model_endpoint_clients")

    assert clients.is_response_format_rejection(error) is expected


def test_sanitized_custom_errors_keep_whether_json_mode_was_refused(initialized_application):
    clients = importlib.import_module("model_endpoint_clients")

    refused = clients._sanitized_custom_request_error(_format_refused(), api_type="openai")
    other = clients._sanitized_custom_request_error(
        _provider_error(param="messages", code=None, message="Invalid messages."), api_type="openai",
    )

    assert clients.is_response_format_rejection(refused) is True
    assert clients.is_response_format_rejection(other) is False
    assert "response_format" not in str(refused)


# ------------------------------------------------------------------------------------------
# The single corrective call
# ------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("first_reply", "problem", "code"), [
    (
        "State,Capital\nAlabama,Montgomery\nAlaska,Juneau",
        "Your previous reply could not be used: it was not one valid JSON object.", None,
    ),
    (
        json.dumps({"rows": "State,Capital\nAlabama,Montgomery\nAlaska,Juneau"}),
        'Your previous reply could not be used: output "rows" was not a JSON array of row objects.',
        "result_records_invalid",
    ),
    (
        json.dumps({"rows": [{"state": "Alabama", "capital": "Montgomery"}]}),
        'Your previous reply could not be used: output "rows" did not match its declared columns or schema.',
        "result_schema_invalid",
    ),
    (
        json.dumps({"table": ROWS}),
        "Your previous reply could not be used: its keys were not exactly the declared output names.",
        "result_output_missing",
    ),
])
def test_a_reply_that_breaks_a_declared_rule_gets_one_corrective_call(
    harness, monkeypatch, first_reply, problem, code,
):
    events = _capture(monkeypatch, "functions_orchestration_composition")

    saved = _run_csv(harness, [first_reply, json.dumps({"rows": ROWS})])

    calls = _compose_calls(harness)
    assert saved["status"] == "completed", saved.get("failure")
    assert len(calls) == 2
    assert all(call["response_format"] == {"type": "json_object"} for call in calls)
    retry = calls[1]["messages"]
    assert retry[:-2] == calls[0]["messages"]
    assert retry[-2] == {"role": "assistant", "content": first_reply}
    assert retry[-1]["role"] == "user"
    correction = retry[-1]["content"]
    assert correction.startswith(problem)
    assert 'Reply again with only one JSON object whose keys are exactly "rows", and no other text.' in correction
    assert 'Output "rows" is a JSON array with one object per row, not CSV or table text.' in correction
    assert _file_bytes(harness, ".csv").decode("utf-8").splitlines() == CSV_LINES
    retries = [kwargs["extra"] for _message, kwargs in events if kwargs.get("extra", {}).get("reason") == "compose_output_retry"]
    assert len(retries) == 1
    assert retries[0]["capability_id"] == "compose"
    assert retries[0].get("execution_code") == code
    assert retries[0]["run_id_hash"] == _hash("run-1") and retries[0]["step_id_hash"] == _hash("rows")
    assert "run_id" not in retries[0] and "step_id" not in retries[0]
    assert "Alabama" not in repr(events)


def test_a_second_unusable_reply_fails_cleanly_without_a_third_call(harness, monkeypatch):
    events = _capture(monkeypatch, "functions_orchestration_composition")
    bad = json.dumps({"rows": f"State,Capital\n{SECRET_REPLY_TEXT},Montgomery"})

    saved = _run_csv(harness, [bad, bad])

    step = _saved_steps(harness)["rows"]
    assert saved["status"] == "failed"
    assert step["status"] == "failed" and step["failure"]["code"] == "result_invalid"
    assert len(_compose_calls(harness)) == 2 and harness.replies == []
    assert _files(harness, ".csv") == []
    failures = [
        kwargs["extra"] for message, kwargs in events if message.endswith("Content preparation could not complete.")
    ]
    assert len(failures) == 1
    assert failures[0]["failure_code"] == "result_invalid"
    assert failures[0]["execution_code"] == "result_records_invalid"
    assert failures[0]["capability_id"] == "compose" and failures[0]["error_type"] == "ResultContractError"
    assert failures[0]["run_id_hash"] == _hash("run-1") and failures[0]["step_id_hash"] == _hash("rows")
    assert "run_id" not in failures[0] and "step_id" not in failures[0]
    assert SECRET_REPLY_TEXT not in repr(events)


def test_no_corrective_call_is_made_when_it_would_not_fit(harness, monkeypatch):
    kind, plan = _plan_request(harness, [_csv_plan()], message="create a csv of states and capitals")
    assert kind == "plan"
    _store(harness, plan, replies=[json.dumps({"rows": "State,Capital"}), json.dumps({"rows": ROWS})])
    budget = importlib.import_module("functions_workflow_context")
    original = budget.calculate_workflow_context_budget
    audits = []

    def audit(messages, *args, **kwargs):
        result = original(messages, *args, **kwargs)
        audits.append(len(messages))
        return {**result, "decision": "full_input" if len(audits) == 1 else "reduced_input"}

    monkeypatch.setattr(budget, "calculate_workflow_context_budget", audit)

    harness.prepare().execute()

    step = _saved_steps(harness)["rows"]
    assert harness.read()["status"] == "failed"
    assert step["failure"]["code"] == "result_invalid"
    assert len(_compose_calls(harness)) == 1 and len(harness.replies) == 1
    assert len(audits) == 2 and audits[1] == audits[0] + 2


def test_an_empty_reply_is_a_model_failure_and_is_never_retried(harness):
    saved = _run_csv(harness, ["", json.dumps({"rows": ROWS})])

    assert saved["status"] == "failed"
    assert saved["failure"]["code"] == "model_failed"
    assert len(_compose_calls(harness)) == 1 and len(harness.replies) == 1
    assert _files(harness, ".csv") == []


def _store_visual(harness, replies, *, kind="diagram", requested="explicit", multiple_outputs=False):
    step = compose_step("schedule")
    step["arguments"].update(
        instruction="Transform the supplied prior nutrition plan into eating and drinking lanes with relative times.",
        knowledge_basis="general_knowledge",
    )
    step["delivers"] = ["answer", "visual"]
    if multiple_outputs:
        step["outputs"].append({"name": "notes", "kind": "text-v1"})
    plan = _normalize(harness, {
        "deliverables": [
            {"id": "answer", "kind": "answer", "requested": "explicit",
             "description": "The updated nutrition plan.", "status": "planned"},
            {"id": "visual", "kind": kind, "requested": requested,
             "description": "A two-lane eating and drinking timeline.", "status": "planned"},
        ],
        "steps": [step], "final_response": input_binding("schedule"),
    })
    _store(harness, plan, replies=replies, history=[PRIOR_PLAN])
    return plan


def _visual_answers(harness):
    return [message for message in harness.assistant_messages() if message["id"] != PRIOR_PLAN["id"]]


def test_a_missing_timeline_gets_one_correction_and_reaches_the_answer(harness, monkeypatch):
    events = _capture(monkeypatch, "functions_orchestration_composition")
    _store_visual(harness, [f"Here is the plan. {SECRET_REPLY_TEXT}", TIMELINE])

    harness.prepare().execute()

    saved = harness.read()
    (answer,) = _visual_answers(harness)
    calls = _compose_calls(harness)
    assert saved["status"] == saved["outcome"] == "completed"
    assert saved["deliverable_states"] == [{"id": "visual", "state": "delivered"}]
    assert TIMELINE.strip() in answer["content"] and "Not delivered" not in answer["content"]
    assert len(calls) == 2
    assert calls[1]["messages"][:-2] == calls[0]["messages"]
    assert calls[1]["messages"][-2]["content"].endswith(SECRET_REPLY_TEXT)
    correction = calls[1]["messages"][-1]["content"]
    assert "explicitly requested visual" in correction and "```mermaid```" in correction
    assert "Return only the complete prepared text." in correction
    assert all("response_format" not in call for call in calls)
    first_prompt = "\n".join(message["content"] for message in calls[0]["messages"])
    assert PRIOR_PLAN["content"] in first_prompt
    assert "[MERMAID_DIAGRAM_GUIDANCE]" in first_prompt
    assert "[PROACTIVE_ANALYTICAL_CHART_GUIDANCE]" not in first_prompt
    retries = [kwargs["extra"] for _message, kwargs in events
               if kwargs.get("extra", {}).get("reason") == "compose_visual_retry"]
    assert len(retries) == 1 and retries[0]["step_id_hash"] == _hash("schedule")
    assert SECRET_REPLY_TEXT not in repr(events) and "Breakfast" not in repr(events)


def test_a_second_visual_omission_keeps_the_answer_and_partial_delivery(harness):
    _store_visual(harness, ["First prose answer.", "The revised prose answer."])

    harness.prepare().execute()

    saved = harness.read()
    (answer,) = _visual_answers(harness)
    assert saved["outcome"] == "partial"
    assert saved["failure"]["code"] == "visual_not_delivered"
    assert saved["deliverable_states"] == [{
        "id": "visual", "state": "not_delivered", "message": "The answer did not include it.",
    }]
    assert "The revised prose answer." in answer["content"] and "Not delivered" in answer["content"]
    assert saved["redraw_step_ids"] == ["schedule"]
    assert len(_compose_calls(harness)) == 2


def test_a_missing_native_chart_is_corrected_without_accepting_a_diagram(harness):
    charts = importlib.import_module("functions_chart_operations")
    chart = charts.build_inline_chart_markdown({
        "version": 1, "kind": "line", "chartType": "line", "chartId": "fuel",
        "title": "Supplied snack timing",
        "data": {"labels": ["Ride"], "datasets": [{"label": "Minutes between snacks", "data": [30]}]},
    })
    _store_visual(harness, [TIMELINE, chart], kind="chart")

    harness.prepare().execute()

    calls = _compose_calls(harness)
    assert harness.read()["deliverable_states"] == [{"id": "visual", "state": "delivered"}]
    assert len(calls) == 2 and "```simplechart```" in calls[1]["messages"][-1]["content"]


@pytest.mark.parametrize(("requested", "reply"), [("suggested", "Only prose."), ("explicit", TIMELINE)])
def test_suggested_or_already_included_visuals_do_not_trigger_correction(harness, requested, reply):
    _store_visual(harness, [reply], requested=requested)

    harness.prepare().execute()

    assert harness.read()["status"] == "completed"
    assert len(_compose_calls(harness)) == 1


@pytest.mark.parametrize("first_reply", [
    "Not a JSON object.",
    json.dumps({"answer": "Only prose.", "notes": "Keep existing quantities."}),
])
def test_shape_and_visual_corrections_share_one_retry(harness, first_reply):
    final_reply = json.dumps({"answer": TIMELINE, "notes": "Keep existing quantities."})
    _store_visual(harness, [first_reply, final_reply], multiple_outputs=True)

    harness.prepare().execute()

    calls = _compose_calls(harness)
    assert harness.read()["deliverable_states"] == [{"id": "visual", "state": "delivered"}]
    assert len(calls) == 2
    assert all(call["response_format"] == {"type": "json_object"} for call in calls)
    assert "```mermaid```" in calls[1]["messages"][-1]["content"]
    correction = calls[1]["messages"][-1]["content"]
    assert "JSON object" in correction and '"answer"' in correction and '"notes"' in correction


def test_a_shape_correction_that_still_omits_the_visual_does_not_get_a_third_call(harness):
    _store_visual(harness, ["Not JSON.", json.dumps({"answer": "Still prose.", "notes": "Notes."})],
                  multiple_outputs=True)

    harness.prepare().execute()

    (answer,) = _visual_answers(harness)
    assert harness.read()["outcome"] == "partial" and "Still prose." in answer["content"]
    assert len(_compose_calls(harness)) == 2


def test_a_visual_correction_must_still_match_the_declared_json_outputs(harness):
    _store_visual(harness, [json.dumps({"answer": "Only prose.", "notes": "Notes."}), "Not JSON."],
                  multiple_outputs=True)

    harness.prepare().execute()

    assert _saved_steps(harness)["schedule"]["failure"]["code"] == "result_invalid"
    assert len(_compose_calls(harness)) == 2


def test_a_visual_correction_that_would_not_fit_keeps_the_valid_partial_answer(harness, monkeypatch):
    _store_visual(harness, ["The usable prose answer."])
    budget = importlib.import_module("functions_workflow_context")
    original = budget.calculate_workflow_context_budget
    audits = []

    def audit(messages, *args, **kwargs):
        result = original(messages, *args, **kwargs)
        audits.append(len(messages))
        return {**result, "decision": "full_input" if len(audits) == 1 else "reduced_input"}

    monkeypatch.setattr(budget, "calculate_workflow_context_budget", audit)

    harness.prepare().execute()

    (answer,) = _visual_answers(harness)
    assert harness.read()["outcome"] == "partial" and "The usable prose answer." in answer["content"]
    assert len(_compose_calls(harness)) == 1
    assert len(audits) == 2 and audits[1] == audits[0] + 2


@pytest.mark.parametrize("stop", ["access", "cancellation"])
def test_visual_correction_rechecks_access_and_cancellation_before_another_call(harness, monkeypatch, stop):
    _store_visual(harness, ["Only prose.", TIMELINE])
    execution = harness.prepare()
    budget = importlib.import_module("functions_workflow_context")
    original = budget.calculate_workflow_context_budget
    audits = []
    cancelled = []

    def audit(messages, *args, **kwargs):
        result = original(messages, *args, **kwargs)
        audits.append(len(messages))
        if len(audits) == 2:
            if stop == "access":
                harness.conversations.items[("conversation-1", "conversation-1")]["user_id"] = "another-owner"
            else:
                cancelled.append(True)
        return result

    monkeypatch.setattr(budget, "calculate_workflow_context_budget", audit)
    monkeypatch.setattr(execution.lease, "cancel_requested", lambda: bool(cancelled))

    execution.execute()

    assert len(audits) == 2
    assert len(_compose_calls(harness)) == 1 and harness.replies == [TIMELINE]
    answers = _visual_answers(harness)
    assert not any("```mermaid" in message["content"] for message in answers)


def test_visual_omission_checks_use_only_explicit_enabled_markdown_deliverables(initialized_application):
    deliverables = importlib.import_module("functions_orchestration_deliverables")
    step = {
        "outputs": [{"name": "answer", "kind": "markdown-v1"}, {"name": "notes", "kind": "text-v1"}],
        "deliverable_context": [
            {"relation": "delivers", "requested": "explicit", "kind": "diagram"},
            {"relation": "delivers", "requested": "suggested", "kind": "chart"},
            {"relation": "unavailable", "requested": "explicit", "kind": "chart"},
            {"relation": "delivers", "requested": "explicit", "kind": "image"},
            {"relation": "delivers", "requested": "explicit", "kind": "chart", "enabled": False},
        ],
    }
    missing = deliverables.missing_compose_visuals(step, {"answer": "Prose.", "notes": TIMELINE})
    assert missing == ["diagram"]
    missing = deliverables.missing_compose_visuals(step, {"answer": TIMELINE})
    assert missing == []
    step["enabled"] = False
    missing = deliverables.missing_compose_visuals(step, {"answer": "Prose."})
    assert missing == []
