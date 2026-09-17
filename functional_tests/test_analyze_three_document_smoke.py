# test_analyze_three_document_smoke.py
"""
Fresh three-document Analyze producer, saved-result, and export regression.
Version: 0.261.114
Implemented in: 0.261.114

Original fictional source text passes through the production narrative producer,
collector, saved section reader, and export builders. Only source I/O and model
completions are deterministic. This is not live model or deployed UI acceptance.
"""

import csv
import io
import json
import re
from copy import deepcopy

from test_analyze_backend_saved_integration import runner_namespace
from test_document_analysis_final_results import run_analysis
from test_saved_analysis_service import ChatSections, saved
from test_support.document_analysis import USER_ID, FixtureAnalysisClient, document_analysis_runtime, original_document


PROMPT = (
    "Use Analyze on the three selected documents. Explain the main risks in these "
    "documents. Include source references and a concise table. Do not invent scores. "
    "Also provide Markdown and CSV outputs."
)
PASSAGES = {
    "supplier": "Northstar Components is the sole Orion sensor assembly supplier; no qualified alternative.",
    "terms": "USD 10,000 one-time convenience termination fee. Renewal and expiry dates are unstated in these documents.",
    "governance": "Maya Chen is the assigned owner; quarterly reviews are an existing control.",
}
FINDINGS = {
    "supplier": [("supplier_dependency", {
        "finding": "Sole supplier dependency",
        "explanation": "Northstar Components is the sole Orion sensor assembly supplier; no qualified alternative.",
    })],
    "terms": [
        ("termination_fee", {
            "finding": "One-time convenience termination cost",
            "explanation": "USD 10,000 one-time convenience termination fee.",
        }),
        ("unstated_dates", {
            "finding": "Dates require confirmation",
            "explanation": "Renewal and expiry dates are unstated; this does not establish that contractual clauses are absent.",
        }),
    ],
    "governance": [("existing_controls", {
        "finding": "Existing ownership and review controls",
        "explanation": "Maya Chen is the assigned owner; quarterly reviews are an existing control.",
    })],
}


def source_completion(prompt):
    excerpt = prompt.split("<DocumentSlice>\n", 1)[1].rsplit("\n</DocumentSlice>", 1)[0]
    findings = []
    for match in re.finditer(r"\[(?:Page \d+, )?Chunk (\d+)\] ([^\n]+)", excerpt):
        chunk, quote = match.groups()
        source = next(name for name, passage in PASSAGES.items() if passage == quote)
        findings.extend({
            "finding_key": key, "values": values, "status": "supported", "issues": [],
            "evidence": [{"chunk_sequence": int(chunk), "quote": quote}],
        } for key, values in FINDINGS[source])
    return json.dumps({"findings": findings})


def test_fresh_three_document_findings_survive_save_reload_and_both_export_formats():
    documents = {
        name: original_document(name, [passage], scope="group", scope_id="isolated-analysis-qa")
        for name, passage in PASSAGES.items()
    }
    client = FixtureAnalysisClient(response_builder=source_completion)
    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(runtime, documents, client, analysis_prompt=PROMPT)
        records = result["authoritative_result"]["value"]
        assert len(records) == 4
        assert {record["document_id"] for record in records} == set(PASSAGES)
        assert result["analysis_validation"]["status"] == "valid"
        assert result["analysis_validation"]["coverage"]["completed_sources"] == 3
        assert len(client.calls) == 3
        assert {call["stage"] for call in client.calls} == {"window_analysis"}
        source_reads = list(runtime.source_reads)
        assert [document_id for kind, document_id in source_reads if kind == "chunks"] == list(PASSAGES)

        uploads = {}

        def upload(**kwargs):
            uploads[kwargs["output_format"]] = kwargs["file_content"].encode("utf-8")
            return {"message": {"id": f"fresh-artifact-{kwargs['output_format']}", "file_name": kwargs["file_name"]}}

        producer = {"kind": "chat", "conversation_id": "fresh-three-source-chat", "message_id": "fresh-analysis"}
        exports = runner_namespace(upload_generated_analysis_artifact_for_current_user=upload)
        artifacts = exports["_maybe_create_document_analysis_generated_artifacts"](
            result, PROMPT, conversation_id=producer["conversation_id"], analysis_producer=producer,
        )
        assert artifacts["assistant_reply"] == result["analysis_reply"]
        expected_rows = runtime.results.get_document_analysis_export_rows(result)
        assert list(csv.DictReader(io.StringIO(uploads["csv"].decode("utf-8")))) == expected_rows
        assert result["analysis_reply"] in uploads["md"].decode("utf-8")
        for values in (values for findings in FINDINGS.values() for _, values in findings):
            assert values["explanation"] in result["analysis_reply"]
            assert values["explanation"] in uploads["md"].decode("utf-8")
        assert "end_chunk_sequence" not in uploads["md"].decode("utf-8")
        assert "end_chunk_sequence" not in uploads["csv"].decode("utf-8")
        assert all("score" not in key.lower() for row in expected_rows for key in row)

        sources = result["analysis_sources"]
        sections = ChatSections()

        def authorize(actor, conversation):
            assert actor == USER_ID and conversation == producer["conversation_id"]
            return {"id": conversation, "user_id": USER_ID}

        def resolve(document_ids, **kwargs):
            assert set(document_ids) == set(PASSAGES)
            return [{**deepcopy(source), "authorization_status": "authorized"} for source in sources]

        descriptor = saved.save_chat_analysis(
            {"reply": result["reply"], "analysis_result": result},
            user_id=USER_ID, conversation_id=producer["conversation_id"], message_id=producer["message_id"],
            authorize_conversation=authorize, save_result=sections.save, source_resolver=resolve,
        )
        message = {
            "id": producer["message_id"], "conversation_id": producer["conversation_id"],
            "role": "assistant", "content": result["reply"], "metadata": {"saved_analysis": descriptor},
        }

        def load_message(actor, conversation, message_id):
            authorize(actor, conversation)
            assert message_id == producer["message_id"]
            return message

        reloaded = ChatSections(deepcopy(sections.contents))
        context = saved.saved_analysis_context(descriptor)
        options = {"message_loader": load_message, "chat_loader": reloaded.load, "source_resolver": resolve}
        page = saved.read_saved_analysis_page(USER_ID, context, **options)
        assert page["total_records"] == 4 and descriptor["source_count"] == 3
        assert [record["values"] for record in page["records"]] == expected_rows
        for record in page["records"]:
            evidence = saved.read_saved_analysis_page(
                USER_ID, context, representation="evidence", record_id=record["record_id"], **options,
            )
            assert evidence["evidence"]
        payload, _ = saved.load_saved_analysis_input(USER_ID, context, **options)
        assert len(json.loads(payload)["records"]) == 4
        assert json.loads(payload)["original_sources_reanalyzed"] is False
        assert len(client.calls) == 3 and runtime.source_reads == source_reads
