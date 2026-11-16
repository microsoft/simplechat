# test_orchestration_native_citation_delivery.py
"""Native workbook inventory to composition, saved message and replayed delivery.

Version: 0.261.417
Implemented in: 0.261.417
Real producers/readers/publication use the existing offline external-I/O harness.
"""

from copy import deepcopy
import importlib
import json

import pytest

from functions_citation_tracking import build_cited_source_subsets
from functions_orchestration_execution import refresh_harness_delivery
from functions_orchestration_result_contracts import ResultRef
from functions_orchestration_result_runtime import read_native_citation_evidence
from test_excel_inventory_persistence import inventory_store, review_workbook
from test_orchestration_attachment_native_evidence import configure_inventory
from test_orchestration_harness_execution import harness, initialized_application
from test_support.orchestration_harness_execution import compose_step, decoded_frames, input_binding


__all__ = ["harness", "initialized_application", "inventory_store", "review_workbook"]


@pytest.mark.parametrize("delivery", ["execute", "refresh"])
def test_native_evidence_identity_survives_composition_saved_publication_and_reconciliation(
    harness, monkeypatch, inventory_store, review_workbook, delivery,
):
    step, _, document = configure_inventory(None, monkeypatch, inventory_store, review_workbook)
    document["_etag"] = "source-revision-1"
    screening = importlib.import_module("content_screening.access")
    mixed = importlib.import_module("functions_mixed_source_orchestration")

    def read_document(document_id, user_id, **kwargs):
        if document_id != "document-1" or user_id != "owner":
            raise PermissionError("The selected workbook is unavailable.")
        return deepcopy(document)

    monkeypatch.setattr(screening, "_read_authorized_document", read_document)
    monkeypatch.setattr(mixed, "_default_document_context_batch_resolver", lambda **kwargs: [
        {"document": read_document(identifier, kwargs["user_id"]), "scope": "personal",
         "group_id": None, "public_workspace_id": None}
        for identifier in kwargs["document_ids"]
    ])
    answer = []

    def reply():
        payload = json.loads(harness.model_calls[-1]["messages"][-1]["content"])
        citations = payload["inputs"]["comments"]["document_citations"]
        root = next(citation for citation in citations if citation.get("annotation_id") == "{root-budget}")
        assert root["location_label"] == "Location"
        assert "native_evidence" not in root
        answer.append("The reviewer requests 19500. " + root["citation"])
        return answer[-1]

    harness.create([
        step, compose_step(inputs={"comments": {"binding": input_binding("comments", "prepared"), "allow_partial": False}}),
    ], replies=[reply], final_response=input_binding("prepare"), user_message="Read the workbook comments.",
        resolved_message="Read the workbook comments.", seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"})
    execution = harness.prepare()
    try:
        if delivery == "execute":
            frames = execution.execute()
        else:
            result = harness.run_engine(execution)
            assert result["status"] == "completed", result
            message_id = f'assistant_orchestration_{harness.execution.fingerprint("run-1")[:40]}'
            execution.lease.publish_message({
                "id": message_id, "conversation_id": "conversation-1", "role": "assistant",
                "content": "Awaiting retained delivery.", "timestamp": "2026-11-06T12:00:00+00:00",
                "metadata": {"orchestration": {"run_id": "run-1", "status": "completed"}},
                **execution.answer_model.metadata(),
            })
            record = execution.lease.update({
                "citations": [], "assistant_message_id": message_id,
                "assistant_message_created_at": "2026-11-06T12:00:00+00:00",
                "message_saved": True, "finalization_status": "saved",
            })
            services = harness.services()
            with harness.publication_only(services):
                frames = refresh_harness_delivery(record, services=services, settings=harness.settings, lease=execution.lease)
        done = decoded_frames(frames)[-1]
        assert done["status"] == "completed", done
        message = harness.assistant_messages()[0]
        citations = message["hybrid_citations"]
        assert citations == done["hybrid_citations"] == harness.read()["citations"]
        assert message["content"] == done["full_content"] == answer[-1]
        root = next(citation for citation in citations if citation.get("annotation_id") == "{root-budget}")
        assert root["document_id"] == "document-1" and root["source_version"] == 1
        evidence = read_native_citation_evidence(
            harness.services().results, ResultRef.from_dict(root["native_evidence"]),
            citation_id=root["citation_id"], document_id=root["document_id"],
        )
        assert evidence["native_annotation"]["text"] == "Set cap to 19500."
        assert evidence["native_annotation"]["cell_value"] == 15000
        tracked = build_cited_source_subsets(message["content"], citations)["cited_hybrid_citations"]
        assert len(tracked) == 1 and tracked[0]["native_evidence"] == root["native_evidence"]
        ambiguous = build_cited_source_subsets("(Source: review.xlsx, Location: Budget!B4)", citations)
        assert ambiguous["cited_hybrid_citations"] == []
        assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0
    finally:
        execution.close()
