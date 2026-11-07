# test_saved_analysis_bounded_reports.py
"""
Behavioral saved-result paging, support and partial-result regressions.
Version: 0.261.109
Implemented in: 0.261.109

The real narrative producer and serialized result sections survive a fresh
reader. Only source I/O and the selected provider callbacks are offline doubles.
"""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from test_analyze_backend_saved_integration import budget, saved
from test_analysis_answer_and_export_data import docx_markdown_renderer
from test_saved_analysis_service import ChatSections
from test_support.document_analysis import (
    USER_ID, FixtureAnalysisClient, document_analysis_runtime, extract_fixture_findings, original_document,
)


def produce_saved(*, count=6, width=125000, partial=False):
    documents = {
        f"source-{index}": original_document(
            f"source-{index}",
            ["There is an exit penalty when changing providers." if index == count - 1 else
             "The contract relies on a sole supplier for spare parts."],
        ) for index in range(count)
    }
    documents["no-findings"] = original_document("no-findings", ["This source has no identified finding."])

    def extracted(prompt):
        response = json.loads(extract_fixture_findings(prompt))
        for finding in response["findings"]:
            finding["values"]["detail"] = "Complete supporting interpretation. " + "x" * width + " END-OF-RECORD"
        return json.dumps(response)

    client = FixtureAnalysisClient(extracted)
    with document_analysis_runtime(documents) as runtime:
        produced = runtime.producer.run_document_analysis(
            USER_ID, "Explain the risks.", list(documents), client.invoke_prompt,
            doc_scope="personal", window_size=1, max_documents=len(documents),
            result_version="analyze-final-v1",
        )
        source_reads = list(runtime.source_reads)
    if partial:
        produced["analysis_validation"]["status"] = "partial"
        produced["analysis_validation"]["limitations"].append("One required source window failed.")
        produced["coverage"]["progress_meta"]["status"] = "partial"
    sources = {source["document_id"]: source for source in produced["analysis_sources"]}
    state = {"allowed": True, "source_reads": source_reads}

    def resolve(ids, **kwargs):
        return [{
            **sources[document_id],
            "authorization_status": "authorized" if state["allowed"] else "unresolved",
        } for document_id in ids]

    store = ChatSections()
    descriptor = saved.save_chat_analysis(
        {"reply": produced["reply"], "analysis_result": produced},
        user_id=USER_ID, conversation_id="conversation-1", message_id="assistant-1",
        authorize_conversation=lambda *args: None, save_result=store.save, source_resolver=resolve,
    )
    original_records = deepcopy(produced["authoritative_result"]["value"])
    del produced
    message = {
        "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
        "metadata": {"saved_analysis": descriptor},
    }
    options = {
        "message_loader": lambda *args: deepcopy(message),
        "chat_loader": ChatSections(deepcopy(store.contents)).load, "source_resolver": resolve,
    }
    context = saved.saved_analysis_context(descriptor)
    reader, _ = saved.load_saved_analysis_input(USER_ID, context, bounded=True, **options)
    return SimpleNamespace(
        reader=reader, state=state, descriptor=descriptor, context=context, options=options,
        records=original_records, store=store, source_model=client,
    )


def configure_model(monkeypatch, context=300000, output=2048):
    monkeypatch.setattr(budget, "resolve_model_token_limits", lambda model, **kwargs: {
        "context_window_tokens": context, "max_input_tokens": context, "max_output_tokens": output,
        "tokenizer": None, "source": "configured", "model_id": model["id"], "status": "known",
    })
    return {"id": "user-selected-custom-model", "responseLength": output}


def report_oracle(fixture, *, omit_record=False, revoke=False, wrong_number=False):
    calls = []
    by_document = {record["document_id"]: record for record in fixture.records}
    last = f"source-{len(fixture.records) - 1}"
    cross_refs = [
        {"result_sha256": fixture.descriptor["result_sha256"], "record_id": by_document[document]["record_id"]}
        for document in ("source-0", last)
    ]

    def invoke(messages, stage=None, metadata=None):
        payload = json.loads(messages[-1]["content"].split("[Saved Analyze result — complete data]\n", 1)[1])
        calls.append({"stage": stage, "payload": deepcopy(payload), "metadata": metadata})
        assert metadata["complete_saved_analysis_input"] is True
        if stage == "saved_analysis_page":
            assert all(record["values"]["detail"].endswith(" END-OF-RECORD") for record in payload["records"])
            entries = [{
                "record_ref": record["record_ref"],
                "text": "The saved value is 987654321." if wrong_number else record["values"]["finding"],
            } for record in payload["records"]]
            if revoke:
                fixture.state["allowed"] = False
            return json.dumps({"record_explanations": entries[:-1] if omit_record else entries})
        if stage == "saved_analysis_conclusions":
            return json.dumps({"conclusions": [
                {"text": "Exit costs make the supplier dependency harder to mitigate.", "supporting_records": cross_refs},
                {"text": "The supplier guarantees uninterrupted service.", "supporting_records": cross_refs},
                {"text": "A record not read proves the opposite.", "supporting_records": [
                    {**cross_refs[0], "record_id": "not-in-this-result"},
                ]},
            ]})
        if stage == "saved_analysis_support":
            records = payload["supporting_records"]
            assert {unit["record"]["document_id"] for unit in records} == {"source-0", last}
            assert all(unit["record"]["values"]["detail"].endswith(" END-OF-RECORD") for unit in records)
            return json.dumps({"supported": payload["conclusion"].startswith("Exit costs")})
        assert stage == "saved_analysis_explanation"
        return "The saved findings identify supplier dependency and exit costs."

    return invoke, calls, cross_refs


def explain(fixture, model, callback):
    return saved.explain_saved_analysis(
        [fixture.reader], [{"role": "user", "content": "Explain how these risks interact."}],
        callback, model=model, provider="aoai", output_tokens=model["responseLength"],
    )


def test_large_report_reads_every_record_and_reloads_cross_page_support(monkeypatch):
    fixture = produce_saved()
    model = configure_model(monkeypatch)
    invoke, calls, cross_refs = report_oracle(fixture)
    report = explain(fixture, model, invoke)
    consumption = report["analysis_consumption"]
    assert consumption["mode"] == "record_pages"
    assert len(consumption["pages"]) > 1
    assert consumption["record_count"] == len(fixture.records)
    seen = [record["record_id"] for call in calls if call["stage"] == "saved_analysis_page" for record in call["payload"]["records"]]
    assert set(seen) == {record["record_id"] for record in fixture.records}
    assert len(seen) == len(set(seen))
    assert consumption["supported_conclusions"][0]["supporting_records"] == cross_refs
    support_pages = [
        index for reference in cross_refs for index, page in enumerate(consumption["pages"])
        if reference in page["record_refs"]
    ]
    assert len(set(support_pages)) == 2
    assert consumption["unsupported_conclusion_count"] == 2
    assert "guarantees uninterrupted" not in report["reply"]
    assert "Exit costs make" in report["reply"]
    assert consumption["deterministic_values"]["accepted_record_count"] == 6
    assert all(audit["model_id"] == "user-selected-custom-model" for audit in consumption["context_budgets"])
    manifest, _, _ = saved.load_saved_analysis(USER_ID, fixture.context, **fixture.options)
    assert manifest["outputs"]["records"]["storage_kind"] == "record_pages"
    assert len(manifest["analysis_access"]["sources"]) == 7
    before = len(fixture.source_model.calls)
    explain(fixture, model, invoke)
    assert len(fixture.source_model.calls) == before
    assert len(fixture.state["source_reads"]) == 14


def test_small_followup_is_one_call_and_partial_records_remain_readable(monkeypatch):
    fixture = produce_saved(count=2, width=20, partial=True)
    model = configure_model(monkeypatch)
    callback, calls, _ = report_oracle(fixture)
    page = saved.read_saved_analysis_page(USER_ID, fixture.context, **fixture.options)
    assert page["validation"]["status"] == "partial" and len(page["records"]) == 2
    report = explain(fixture, model, callback)
    assert report["analysis_consumption"]["model_calls"] == 1
    assert calls[0]["payload"]["accepted_subset_only"] is True
    assert calls[0]["payload"]["execution"]["status"] == "incomplete"


@pytest.mark.parametrize("mode", ["omitted", "revoked", "wrong_number"])
def test_a_page_cannot_omit_records_publish_revoked_data_or_invent_values(monkeypatch, mode):
    fixture = produce_saved()
    model = configure_model(monkeypatch)
    callback, calls, _ = report_oracle(
        fixture, omit_record=mode == "omitted", revoke=mode == "revoked", wrong_number=mode == "wrong_number",
    )
    with pytest.raises((ValueError, PermissionError)):
        explain(fixture, model, callback)
    assert len(calls) == 1


def test_more_than_eight_megabytes_uses_record_pages_not_whole_materialization(monkeypatch):
    fixture = produce_saved(width=1450000)
    with pytest.raises(ValueError, match="explicit record batches"):
        saved.load_saved_analysis_input(USER_ID, fixture.context, **fixture.options)
    model = configure_model(monkeypatch, context=2000000)
    callback, calls, _ = report_oracle(fixture)
    result = explain(fixture, model, callback)
    assert result["analysis_consumption"]["record_count"] == 6
    assert len([call for call in calls if call["stage"] == "saved_analysis_page"]) == 6


@pytest.mark.parametrize("output_format", ["json", "csv", "xml", "md", "docx", "pdf"])
def test_format_only_reads_saved_values_without_any_model_or_source_extraction(output_format, docx_markdown_renderer):
    fixture = produce_saved(count=2, width=20)
    uploads = []
    bindings = []
    before = len(fixture.source_model.calls)

    def upload(**kwargs):
        uploads.append(kwargs)
        return {"message": {"id": "reformatted", "file_name": kwargs["file_name"]}}

    result = saved.format_saved_analysis(
        [fixture.reader], output_format, conversation_id="conversation-1",
        producer=fixture.descriptor["binding"], contexts=[fixture.context],
        upload_artifact=upload, bind_contexts=lambda *args: bindings.append(args),
    )
    assert result["analysis_consumption"]["model_calls"] == 0
    assert len(fixture.source_model.calls) == before
    assert len(fixture.state["source_reads"]) == 6
    assert result["analysis_result"]["authoritative_result"]["value"] == fixture.records
    assert len(bindings) == 1
    assert uploads[0]["file_content"]
    if output_format == "json":
        assert json.loads(uploads[0]["file_content"]) == [record["values"] for record in fixture.records]


def test_correction_audit_never_competes_with_calculated_values_in_default_context():
    fixture = produce_saved(count=2, width=20)
    manifest, load, _ = saved.load_saved_analysis(USER_ID, fixture.context, **fixture.options)
    validation = deepcopy(manifest["validation"])
    validation["issues"] = [{
        "code": "analysis_calculation_value_corrected", "field": "amount",
        "reported_value": 99998765, "calculated_value": 12,
    }]
    records = deepcopy(fixture.records)
    records[0]["values"]["amount"] = 12
    store = ChatSections()
    descriptor = saved.save_chat_analysis(
        {"reply": "The amount is twelve.", "analysis_result": {
            "analysis_result_version": "analyze-final-v1",
            "analysis_sources": manifest["analysis_access"]["sources"],
            "authoritative_result": {"kind": "records", "value": records},
            "analysis_evidence": saved._load_section(manifest, "evidence", load)["value"],
            "analysis_validation": validation,
        }},
        user_id=USER_ID, conversation_id="conversation-1", message_id="corrected",
        authorize_conversation=lambda *args: None, save_result=store.save,
        source_resolver=fixture.options["source_resolver"],
    )
    context = saved.saved_analysis_context(descriptor)
    options = {
        **fixture.options, "chat_loader": ChatSections(deepcopy(store.contents)).load,
        "message_loader": lambda *args: {
            "id": "corrected", "conversation_id": "conversation-1", "role": "assistant",
            "metadata": {"saved_analysis": descriptor},
        },
    }
    payload, _ = saved.load_saved_analysis_input(USER_ID, context, **options)
    assert "99998765" not in payload and '"reported_value"' not in payload
    assert json.loads(payload)["records"][0]["values"]["amount"] == 12
    corrected_manifest, corrected_load, _ = saved.load_saved_analysis(USER_ID, context, **options)
    audit = saved._load_section(corrected_manifest, "diagnostics", corrected_load)["value"]
    assert audit["validation_audit"]["issues"][0]["reported_value"] == 99998765
    evidence = saved.read_saved_analysis_page(
        USER_ID, fixture.context, representation="evidence", record_id=fixture.records[0]["record_id"], **fixture.options,
    )["evidence"][0]
    assert evidence["quote"] == evidence["text"]
    assert evidence["file_name"] == evidence["source"]["file_name"]
    assert evidence["page_number"] == evidence["location"]["page_number"]


def test_per_document_descriptor_counts_flat_final_records_not_document_envelopes():
    fixture = produce_saved(count=2, width=20)
    manifest, load, _ = saved.load_saved_analysis(USER_ID, fixture.context, **fixture.options)
    envelope = saved.build_chat_analysis_result({
        "reply": "Per-document findings.", "analysis_result": {
            "analysis_result_version": "analyze-final-v1", "per_document": True,
            "analysis_sources": manifest["analysis_access"]["sources"],
            "authoritative_result": {"kind": "records", "value": fixture.records},
            "analysis_evidence": saved._load_section(manifest, "evidence", load)["value"],
            "analysis_validation": {"status": "not_requested"},
        },
    }, user_id=USER_ID, conversation_id="conversation-1", message_id="per-document")
    assert envelope["record_count"] == 2
    assert envelope["authoritative_output"] == "records"
    assert envelope["validation"]["status"] == "not_validated"
