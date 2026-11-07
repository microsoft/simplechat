# test_orchestration_document_action_lineage.py
"""
Functional regressions for native document action retention and composition.
Version: 0.261.419
Implemented in: 0.261.419

Real external admission, SDK-default result storage, retained readers, compiler,
executor and composition run with external configuration/model I/O isolated.
Workspace provenance and current integration authority must both survive.
"""

import importlib
import json
import logging
from copy import deepcopy
from types import SimpleNamespace

import pytest

from functions_task_completeness import NARRATIVE_OBLIGATIONS
from test_orchestration_harness_routes import modules
from test_support.orchestration_harness_execution import compose_step, input_binding


__all__ = ["modules"]
ANSWER = "The stored PDF tag flag is false. This does not establish formal conformance."


@pytest.fixture
def native_result(modules):
    from test_orchestration_external_sources import ExternalSourceWorld

    with ExternalSourceWorld("action_invoke") as world:
        action = world.services.records[("actions", "group")][("group-a", "action-1")]
        action["type"] = "document_search"
        step = world.run["plan"]["steps"][0]
        step["arguments"]["document_ids"] = ["document-1"]
        provider = world.provider()
        service = world.service(provider)
        context = SimpleNamespace(
            result_service=service, action_catalog=world.catalog("owner", settings=world.settings),
            result_producer=lambda current: world.fixture.producer,
            result_guard_token_for_step=lambda step_id: "server-attempt-token",
            result_input_fingerprint_for_step=lambda step_id: None,
            external_source_admission=lambda **kwargs: provider.admit_gather_result(
                **kwargs, selector=world.action_selector,
            ),
        )
        citations = importlib.import_module("functions_agent_document_citations")
        payload = citations.annotate_document_search_payload({
            "document": {"id": "document-1", "file_name": "selected.pdf", "version": 1},
            "scope": "personal",
            "accessibility_metadata": {
                "format": "pdf", "is_tagged": False,
                "inspection_limits": ["Formal conformance is not determined by this metadata."],
            },
        }, "get_document_accessibility_report")
        result = {
            "status": "completed", "notes": [json.dumps(payload)], "citations": [{
                "plugin_name": "document_search", "function_name": "get_document_accessibility_report",
                "function_result": payload, "success": True,
            }],
        }
        yield SimpleNamespace(
            world=world, provider=provider, service=service, context=context,
            step=step, result=result, payload=payload,
            sources=[deepcopy(world.fixture.sources["document-1"])],
        )


def retain(case):
    runtime = importlib.import_module("functions_orchestration_result_runtime")
    return runtime.retain_gather_result(
        case.step, case.context, case.result, source_manifest=case.sources,
    )


def test_native_action_keeps_workspace_and_external_lineage_after_restart(native_result):
    case = native_result
    task = retain(case)
    reader = case.world.service(case.provider).open_result(task.output("prepared"))
    value = reader.read_value()
    metadata = reader.metadata()
    sources = reader.lineage_sources()
    assert value["notes"] == case.result["notes"]
    assert metadata["source_count"] == metadata["external_source_count"] == 1
    assert metadata["origin"] == "grounded"
    assert sources == case.sources
    assert case.payload["citation"] in value["notes"][0]
    case.world.services.roles.clear()
    with pytest.raises(PermissionError):
        case.world.service(case.provider).open_result(task.output("prepared"))


@pytest.mark.parametrize("kind", ["wrong_action", "missing_binding", "missing_source", "wrong_source"])
def test_other_integrations_and_mismatched_lineage_are_rejected(native_result, kind):
    case = native_result
    if kind == "wrong_action":
        case.context.action_catalog[0]["type"] = "openapi"
    elif kind == "missing_binding":
        case.step["arguments"].pop("document_ids")
    elif kind == "missing_source":
        case.sources = []
    else:
        case.step["arguments"]["document_ids"] = ["other-document"]
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    with pytest.raises(contracts.ResultContractError) as failure:
        retain(case)
    assert failure.value.code == "result_external_lineage_unsupported"
    assert not case.world.fixture.container.items


@pytest.mark.parametrize("checks_enabled", [False, True])
@pytest.mark.parametrize("debug", [False, True])
def test_bound_native_findings_reach_the_final_composed_answer(
    native_result, checks_enabled, debug, monkeypatch, caplog,
):
    case = native_result
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.orchestration.native.lineage")
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": debug})
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    caplog.set_level(logging.INFO, logger=logger.name)
    task = retain(case)
    registry = importlib.import_module("functions_orchestration_registry")
    schema = importlib.import_module("functions_orchestration_schema")
    executor = importlib.import_module("functions_orchestration_executor")
    capabilities = importlib.import_module("functions_model_capabilities")
    output = task.output("prepared")
    answer = compose_step("answer", inputs={
        "native_findings": {
            "binding": {
                "version": "orchestration-input-binding-v1", "step_id": None,
                "output_name": None, "existing_result": "native_report",
            },
            "allow_partial": False,
        },
    })
    answer["arguments"].update(
        knowledge_basis="sources", instruction="Report the native flag and its limitations.",
        response_policy="available_information",
    )
    plan = schema.normalize_plan({
        "run_id": "answer-run", "plan_id": "answer-plan", "steps": [answer],
        "final_response": input_binding("answer"),
    }, "conversation-1", "owner", available_capability_ids=["compose"],
        existing_results={"native_report": output}, contract_version=2)
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    producer = contracts.ProducerIdentity(
        "owner", "conversation-1", "answer-run", 1, "answer", "compose",
        registry.get_capability("compose")["result_contract_version"],
    )
    case.world.fixture.add_producer(producer)
    case.world.fixture.runs["answer-run"]["plan"] = plan

    class Model:
        model_metadata = capabilities.ModelTokenBudget(
            model_id="offline-composition", provider="openai", context_window=32768,
            input_limit=24576, output_limit=2048, output_accounting="total_generation",
        )
        provider = "openai"
        output_tokens = 512

        def __init__(self):
            self.calls = []

        def __call__(self, messages, **kwargs):
            self.calls.append(deepcopy(messages))
            if messages[0]["content"].startswith("Prepare only"):
                return f"{ANSWER} {case.payload['citation']}"
            return json.dumps({"requirements": [{
                "id": identifier, "requirement": requirement, "status": "satisfied",
                "reason": "", "evidence_refs": [], "answer_quote": ANSWER,
            } for identifier, requirement in NARRATIVE_OBLIGATIONS]})

    model = Model()
    context = executor.RunContext(
        run_id="answer-run", plan_id="answer-plan", conversation_id="conversation-1", user_id="owner",
        user_message="Inspect the native PDF tag flag.", plan_contract_version=2,
        result_service=case.world.service(case.provider), result_aliases={"native_report": output},
        result_guard_token_for_step=lambda step_id: "server-attempt-token", invoke_prompt=model,
    )
    result = executor.execute_plan(
        plan, context, settings={"enable_chat_orchestration_completeness_check": checks_enabled},
        user_id="owner",
    )
    assert result["status"] == "completed", result
    assert ANSWER in result["message"] and case.payload["citation"] in result["message"]
    assert len(model.calls) == (2 if checks_enabled else 1)
    sent = json.loads(model.calls[0][-1]["content"])
    retained = sent["inputs"]["native_findings"]["value"]
    citations = sent["inputs"]["native_findings"]["document_citations"]
    native = json.loads(retained["notes"][0])
    assert native["accessibility_metadata"]["is_tagged"] is False
    assert native["accessibility_metadata"]["inspection_limits"] == (
        case.payload["accessibility_metadata"]["inspection_limits"]
    )
    assert native["citation"] == case.payload["citation"]
    assert len(citations) == 1
    assert citations[0]["document_id"] == "document-1"
    assert citations[0]["citation"] == case.payload["citation"]
    stages = {"gather_retention", "gather_retained", "retained_citation_projection", "compose_inputs", "compose_retained"}
    records = [record for record in caplog.records if getattr(record, "sc_stage", None) in stages]
    assert {record.sc_stage for record in records} == (stages if debug else set())
    assert case.world.fixture.source_reads == []
    if debug:
        retained_record = next(record for record in records if record.sc_stage == "gather_retained")
        input_record = next(record for record in records if record.sc_stage == "compose_inputs")
        assert retained_record.sc_workspace_source_count == retained_record.sc_external_source_count == 1
        assert input_record.sc_document_citation_count == 1
        linked = [record for record in records if getattr(record, "sc_consumer_run_id_hash", None)]
        assert linked and all(len(record.sc_consumer_run_id_hash) == 64 for record in linked)
        serialized = json.dumps([
            {name: value for name, value in record.__dict__.items() if name.startswith("sc_")}
            for record in records
        ])
        assert ANSWER not in serialized and "document-1" not in serialized
        assert "selected.pdf" not in serialized and case.payload["citation"] not in serialized


def test_native_tool_citations_cannot_name_another_source(native_result):
    case = native_result
    case.result["citations"][0]["function_result"]["document"]["id"] = "unselected-document"
    task = retain(case)
    runtime = importlib.import_module("functions_orchestration_result_runtime")
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    with pytest.raises(contracts.ResultContractError) as failure:
        runtime.read_result_document_citations(case.context, task.output("prepared"))
    assert failure.value.code == "result_citation_source_invalid"
