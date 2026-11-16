# test_orchestration_reason_render_pipeline.py
"""Actual Analyze, Compare and native compute feed explicit multiple-file plans.

Version: 0.261.127
Implemented in: 0.261.127

Use the initialized application, real headless claim/executor, production
producers, retained readers, rendering, private commit and download. Only source,
model and storage I/O are doubled. No adapter, checkpoint or result is fabricated.
"""

import csv
import importlib
import io
import json
from copy import deepcopy

import pytest
from flask import Flask

from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_orchestration_internal_analysis import findings_from_original_source
from test_support.document_analysis import original_document
from test_support.orchestration_harness_execution import decoded_frames, native_step, render_step


def download_outputs(harness):
    services = harness.services()
    routes = importlib.import_module("route_enhanced_citations")
    app = Flask("orchestration-reason-render")
    payloads = {}
    with harness.monkeypatch.context() as patched, harness.publication_only(services):
        patched.setattr(routes, "cosmos_conversations_container", harness.conversations)
        patched.setattr(routes, "cosmos_messages_container", harness.messages)
        outputs = services.rendering.list_public_outputs("run-1")
        artifacts = services.rendering.committed_artifacts("run-1")
        for output in outputs:
            with app.test_request_context():
                response = routes._serve_chat_artifact_download(
                    "owner", "conversation-1", output["artifact_message_id"],
                )
                try:
                    payloads[output["file_name"]] = b"".join(response.response)
                finally:
                    response.close()
    return outputs, artifacts, payloads


@pytest.fixture
def narrative_io(harness, monkeypatch):
    search = importlib.import_module("functions_search_service")
    screening = importlib.import_module("content_screening.access")
    mixed = importlib.import_module("functions_mixed_source_orchestration")
    documents = {
        identifier: original_document(
            identifier, [f"Item {index:03} contains original source detail." for index in range(count)],
        )
        for identifier, count in (("document-1", 7), ("target-1", 3))
    }
    for entry in documents.values():
        entry["document"].update(user_id="owner", _etag="source-revision-1")
    reads = []

    def read_document(document_id, user_id, group_id=None, public_workspace_id=None, **kwargs):
        if (
            user_id != "owner" or document_id not in documents
            or group_id is not None or public_workspace_id is not None
        ):
            raise PermissionError("The selected fixture document is unavailable.")
        reads.append(("metadata", document_id))
        return deepcopy(documents[document_id]["document"])

    def read_chunks(document_id, user_id, **kwargs):
        read_document(document_id, user_id, **kwargs)
        reads.append(("chunks", document_id))
        return deepcopy(documents[document_id]["chunks"])

    monkeypatch.setattr(screening, "_read_authorized_document", read_document)
    monkeypatch.setattr(search, "get_document_record", read_document)
    monkeypatch.setattr(search, "get_ordered_document_chunks", read_chunks)
    monkeypatch.setattr(mixed, "_default_document_context_batch_resolver", lambda **kwargs: [
        {
            "document": read_document(identifier, kwargs["user_id"]), "scope": "personal",
            "group_id": None, "public_workspace_id": None,
        }
        for identifier in kwargs["document_ids"]
    ])

    def model_reply():
        prompt = harness.model_calls[-1]["messages"][-1]["content"]
        if "<DocumentSlice>\n" in prompt:
            return findings_from_original_source(prompt)
        return "# Complete comparison\n\nOriginal source and target findings.\n\nLAST-COMPARISON"

    return {"reads": reads, "reply": model_reply}


def test_actual_analyze_reuses_findings_and_report_for_two_files(harness, narrative_io):
    table = render_step("findings", "csv", source="analyze", output="records")
    table["arguments"]["options"] = {"columns": ["item", "enabled"]}
    harness.create(
        [
            {
                "step_id": "analyze", "capability_id": "document_analyze",
                "arguments": {
                    "document_ids": ["document-1"], "doc_scope": "personal",
                    "analysis_prompt": "Retain every original finding, including the last item.",
                },
                "outputs": [
                    {"name": "findings", "kind": "records-v1"},
                    {"name": "coverage", "kind": "structured-v1"},
                    {"name": "records", "kind": "records-v1"},
                    {"name": "report", "kind": "markdown-v1"},
                ],
            },
            table,
            render_step("report", "md", source="analyze", output="report"),
        ],
        replies=[narrative_io["reply"]] * 20,
        seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
    )
    execution = harness.prepare()
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert done["status"] == "completed", done
    task = execution.context.task_results["analyze"]
    services = harness.services()
    findings = list(services.results.open_result(task.output("records")).iter_records())
    report = services.results.open_result(task.output("report")).read_text()
    before = (len(harness.model_calls), len(narrative_io["reads"]), harness.blobs.file_uploads)
    outputs, artifacts, payloads = download_outputs(harness)
    assert len(outputs) == len(artifacts) == 2
    assert len(findings) == 7 and sorted(row["item"] for row in findings) == [
        f"{index:03}" for index in range(7)
    ]
    assert "Complete finding 006." in report
    assert payloads["report.md"] == report.encode("utf-8")
    assert list(csv.reader(io.StringIO(payloads["findings.csv"].decode("utf-8")))) == [
        ["item", "enabled"], *[[row["item"], str(row["enabled"]).lower()] for row in findings],
    ]
    assert len(harness.model_calls) == before[0] and harness.blobs.file_uploads == before[2] == 2
    assert [entry for entry in narrative_io["reads"][before[1]:] if entry[0] == "chunks"] == []
    assert len(harness.assistant_messages()) == 1 and done["generated_artifacts"] == artifacts


def test_actual_compare_reuses_full_comparison_for_json_and_report(harness, narrative_io):
    harness.create(
        [
            {
                "step_id": "compare", "capability_id": "document_compare",
                "arguments": {
                    "left_document_id": "document-1", "right_document_ids": ["target-1"],
                    "doc_scope": "personal", "comparison_prompt": "Compare all original source details.",
                },
                "outputs": [
                    {"name": "comparison", "kind": "comparison-v1"},
                    {"name": "coverage", "kind": "structured-v1"},
                    {"name": "report", "kind": "markdown-v1"},
                ],
            },
            render_step("comparison", "json", source="compare", output="comparison", profile="structured_value_v1"),
            render_step("report", "md", source="compare", output="report"),
        ],
        replies=[narrative_io["reply"]] * 20,
        seeds={"document_ids": ["document-1", "target-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1", "target-1"], "doc_scope": "personal"},
    )
    execution = harness.prepare()
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert done["status"] == "completed", done
    task = execution.context.task_results["compare"]
    services = harness.services()
    comparison = services.results.open_result(task.output("comparison")).read_value()
    report = services.results.open_result(task.output("report")).read_text()
    before = (len(harness.model_calls), len(narrative_io["reads"]), harness.blobs.file_uploads)
    outputs, artifacts, payloads = download_outputs(harness)
    assert len(outputs) == len(artifacts) == 2 and len(comparison["items"]) == 1
    assert json.loads(payloads["comparison.json"]) == comparison
    assert payloads["report.md"] == report.encode("utf-8") and "LAST-COMPARISON" in report
    assert len(harness.model_calls) == before[0] and harness.blobs.file_uploads == before[2] == 2
    assert [entry for entry in narrative_io["reads"][before[1]:] if entry[0] == "chunks"] == []
    assert len(harness.assistant_messages()) == 1 and done["generated_artifacts"] == artifacts


def test_actual_native_wait_finishes_once_then_renders_two_complete_files(harness):
    harness.settings.update({
        "enable_tabular_generation_plan": False,
        "enable_tabular_completion_driven_checkpointing": False,
        "tabular_generated_output_inline_max_rows": 1,
    })
    with harness.native_io() as native:
        table = render_step("table", "csv", source="compute", output="records")
        table["arguments"]["options"] = {"columns": ["Item_ID", "doubled"]}
        harness.create(
            [native_step(), table, render_step("data", "json", source="compute", output="records")],
            seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare()
        first_frames = first.execute()
        first_done = decoded_frames(first_frames)[-1]
        original = harness.read()
        assert first_done["status"] == "waiting" and harness.blobs.file_uploads == 0
        native.engine.process_tabular_generated_output_run(
            original["pending_results"]["compute"]["handle"]["job_id"], "owner",
        )
        resumed = harness.continue_waiting("render-native-results")
        completed_frames = resumed.execute()
        done = decoded_frames(completed_frames)[-1]
        current = harness.read()
        assert done["status"] == "completed", done
        outputs, artifacts, payloads = download_outputs(harness)
        expected = [{"Item_ID": f"item-{index:06}", "doubled": index * 2} for index in range(1, 38)]
        assert json.loads(payloads["data.json"]) == expected
        assert list(csv.reader(io.StringIO(payloads["table.csv"].decode("utf-8")))) == [
            ["Item_ID", "doubled"], *[[row["Item_ID"], str(row["doubled"])] for row in expected],
        ]
        assert len(outputs) == len(artifacts) == harness.blobs.file_uploads == 2
        assert all(output["row_count"] == 37 for output in outputs)
        assert native.jobs.created == 1 and harness.model_calls == []
        assert current["attempt_index"] == original["attempt_index"] == 1
        assert current["execution_deadline_at"] == original["execution_deadline_at"]
        assert current["task_results"]["compute"]["producer"] == original["task_results"]["compute"]["producer"]
        assert current["pending_results"] == {} and len(harness.assistant_messages()) == 1
        assert done["message_id"] == first_done["message_id"]
