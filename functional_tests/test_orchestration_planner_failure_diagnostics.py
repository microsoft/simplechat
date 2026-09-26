# test_orchestration_planner_failure_diagnostics.py
"""
Functional regressions for planner selection constraints and safe diagnostics.
Version: 0.261.140
Implemented in: 0.261.115
Single orchestration contract updated in: 0.261.139

The real planner, registry, request context, and validator use controlled provider
responses. Tests distinguish missing selected work from malformed/provider output,
without accepting empty plans, switching models, or logging provider secrets.
"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from openai import APIError, APITimeoutError

from test_orchestration_research_selection import ScriptedClient, model_plan, result_binding, result_input
from test_support.orchestration_research import case_inputs, load_case_suite, planner_runtime


PROMPT = (
    "Use Analyze on the three selected documents. Explain the main risks in these "
    "documents. Include source references and a concise table. Do not invent scores. "
    "Also provide Markdown and CSV outputs."
)


@pytest.fixture
def planner_case():
    with planner_runtime() as runtime:
        suite = load_case_suite()
        case = next(item for item in suite["cases"] if item["id"] == "long-simple-drafting")
        settings, caller, context = case_inputs(runtime, suite, case)
        logs = []
        with patch.dict(runtime.planner, {
            "log_event": lambda message, **kwargs: logs.append((message, kwargs)),
        }):
            yield SimpleNamespace(runtime=runtime, settings=settings, caller=caller, context=context, logs=logs)


def plan(fixture, client, *, seeds=None, context=None, authorized=None):
    with patch.dict(fixture.runtime.planner, {
        "resolve_planner_client": lambda settings: (client, "gpt-4o"),
    }):
        return fixture.runtime.planner["plan_request"](
            PROMPT, context or fixture.context, "three-document-chat", fixture.caller["user_id"],
            turn_id="three-document-turn", settings=fixture.settings, request_context=fixture.caller,
            seeds=seeds, authorized_document_ids=authorized, approval_mode="manual",
        )


def failure_log(fixture):
    return next(
        details["extra"] for message, details in reversed(fixture.logs)
        if message == "[ORCHESTRATION_PLANNER] The request could not be planned."
    )


def test_three_pinned_documents_allow_analyze_but_explicit_search_stays_required(planner_case):
    fixture = planner_case
    fixture.settings.update({
        "enable_group_workspaces": True,
        "chat_orchestration_enabled_capabilities": ["document_search", "document_analyze", "compose"],
    })
    ids = ["supplier", "terms", "governance"]
    seeds = {"document_ids": ids}
    context = fixture.runtime.context["build_planner_context"](
        PROMPT, candidates=[{"document_id": document_id, "file_name": f"{document_id}.txt"} for document_id in ids],
        seeds=seeds,
    )
    proposal = model_plan()
    proposal["steps"].insert(0, {
        "step_id": "review", "capability_id": "document_analyze", "title": "Analyze the selected documents",
        "arguments": {"document_ids": ids, "analysis_prompt": PROMPT}, "depends_on": [],
    })
    proposal["steps"][-1]["inputs"] = {"analysis": result_input("review", "findings")}
    proposal["steps"][-1]["arguments"]["knowledge_basis"] = "sources"
    proposal["steps"][-1]["depends_on"] = ["review"]
    proposal["final_response"] = result_binding("draft", "answer")
    client = ScriptedClient(proposal)
    kind, document = plan(fixture, client, seeds=seeds, context=context, authorized=ids)
    assert kind == "plan"
    assert {step["capability_id"] for step in document["steps"]} == {"document_analyze", "compose"}
    assert set(fixture.runtime.schema["plan_document_ids"](document)) == set(ids)
    assert document["approval"]["mode"] == "manual"
    assert len(client.calls) == 1 and client.calls[0]["model"] == "gpt-4o"

    with pytest.raises(fixture.runtime.planner["PlannerError"]):
        plan(fixture, ScriptedClient(proposal), seeds={**seeds, "required_capabilities": ["document_search"]},
             context=context, authorized=ids)
    diagnostic = failure_log(fixture)
    assert diagnostic["reason"] == "invalid_plan_or_missing_requirement"
    assert diagnostic["stage"] == "selected_requirements"
    assert diagnostic["conversation_id_hash"] == hashlib.sha256(b"three-document-chat").hexdigest()
    assert diagnostic["turn_id_hash"] == hashlib.sha256(b"three-document-turn").hexdigest()
    assert "conversation_id" not in diagnostic and "turn_id" not in diagnostic


@pytest.mark.parametrize("reply,reason", [
    ("PRIVATE_UNPARSEABLE_PROVIDER_REPLY", "unparseable_plan"),
    ({"kind": "something_else", "message": "PRIVATE_PROVIDER_REPLY"}, "invalid_planner_response_kind"),
    ({"kind": "plan", "steps": []}, "invalid_plan_work"),
    ({"kind": "plan"}, "invalid_plan_work"),
])
def test_unusable_provider_output_is_not_a_successful_empty_plan(planner_case, reply, reason):
    fixture = planner_case
    client = ScriptedClient(reply)
    with pytest.raises(fixture.runtime.planner["PlannerError"]) as failure:
        plan(fixture, client)
    assert failure_log(fixture)["reason"] == reason
    assert len(client.calls) == 1
    assert "PRIVATE" not in str(failure.value)
    assert "PRIVATE" not in json.dumps(fixture.logs)


@pytest.mark.parametrize("timeout", [False, True])
def test_provider_errors_and_timeouts_keep_safe_type_and_request_identity(planner_case, timeout):
    fixture = planner_case
    request = httpx.Request("POST", "https://private.test/model?key=PRIVATE_PROVIDER_SECRET")
    error = APITimeoutError(request=request) if timeout else APIError(
        "PRIVATE_PROVIDER_SECRET", request=request, body={"error": "PRIVATE_PROVIDER_SECRET"},
    )
    client = ScriptedClient(error)
    with pytest.raises(fixture.runtime.planner["PlannerError"]) as failure:
        plan(fixture, client)
    diagnostic = failure_log(fixture)
    assert diagnostic["stage"] == "model_request"
    assert diagnostic["error_type"] == type(error).__name__
    assert diagnostic["reason"] == "model_request_failed"
    assert len(client.calls) == 1
    assert "PRIVATE" not in str(failure.value)
    assert "PRIVATE" not in json.dumps(fixture.logs)
    assert "private.test" not in json.dumps(fixture.logs)


@pytest.mark.parametrize("finish,content,reason", [
    ("length", '{"kind":"plan"}', "incomplete_completion"),
    ("content_filter", "", "model_refusal"),
    ("stop", "", "empty_completion"),
])
def test_incomplete_refused_and_missing_completions_are_identifiable(planner_case, finish, content, reason):
    fixture = planner_case
    create = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish, message=SimpleNamespace(content=content),
    )])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(fixture.runtime.planner["PlannerError"]):
        plan(fixture, client)
    diagnostic = failure_log(fixture)
    assert diagnostic["response_failure"] == reason
    assert diagnostic["error_type"] == "PlannerResponseError"
