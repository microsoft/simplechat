# workflow_saved_output_publication.py
"""
Closed saved-output publication fixtures for the production V2 SPA.
Version: 0.261.119
Implemented in: 0.261.119

Reuse production definition validation and the publication-completion boundary.
All source records, run facts, artifact metadata, and download bytes are fictional.
No workflow is executed and no document is published to a live workspace.
"""

import copy
import json

import pytest

from ui_tests.fixtures.workflow_control_definitions import flow_binding
from ui_tests.fixtures.workflow_editor import GROUP_ID, editor_options
from ui_tests.fixtures.workflow_loops import loop_workflow_record, record_contract
from ui_tests.fixtures.workflow_publication_completion import (
    WorkflowPublicationFixture,
    connect_options,  # noqa: F401
    execution_id,
    publication_key,
    publication_status,
    publication_workflow_record,
)


SOURCE_CAPABILITIES = [
    {
        "source_kind": "native_analysis",
        "output_kinds": ["records", "json", "text", "document_results"],
        "artifact_formats": ["md", "csv", "json"],
    },
    {
        "source_kind": "saved_output",
        "output_kinds": ["records"],
        "artifact_formats": ["json"],
    },
]
ARTIFACT_CONVERSATION_ID = "saved-output-conversation"
ARTIFACT_MESSAGE_ID = "saved-output-artifact"
ARTIFACT_FILE_NAME = "workflow-output-fixture.json"
ARTIFACT_BYTES = json.dumps([
    {"values": {"finding": "Complete saved finding", "count": 0, "accepted": False, "optional": None},
     "provenance": {"source": "fictional-first"}},
    {"values": {"finding": "Unicode \u00e9 and nested values", "nested": [{"kept": True}]},
     "provenance": {"source": "fictional-second"}},
], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def publication_task(record):
    return next(task for task in record["tasks"] if task["id"] == "publish")


def use_saved_output(record, producer="collect-findings", output="records"):
    task = publication_task(record)
    task["publication"].update(source_kind="saved_output", artifact_format="json")
    task["inputs"] = [flow_binding("deliverable", producer, output, kind="records")]
    return record


def saved_output_workflow_record(scope="user"):
    record = publication_workflow_record(scope)
    loop_record = loop_workflow_record(group=scope == "group")
    generic = {
        "id": "records-task", "type": "instructions", "name": "Prepare saved records",
        "instructions": "Produce exact records without a native Analyze artifact.",
        "runner": {"type": "inherit"}, "inputs": [], "reference_ids": [],
        "document_action": {"type": "none"}, "output_contract": record_contract(),
    }
    record["tasks"].extend([generic, *loop_record["tasks"]])
    for index, task in enumerate(record["tasks"], 1):
        task["order"] = index
    analyze, publish = record["flow"]["nodes"]
    record["flow"]["nodes"] = [
        analyze,
        {"id": "saved-records", "kind": "task", "task_id": generic["id"]},
        *loop_record["flow"]["nodes"],
        {
            "id": "choose-output", "kind": "if", "inputs": [],
            "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
            "then": {"id": "collected-path", "nodes": []},
            "else": {"id": "saved-path", "nodes": []},
            "join": {
                "id": "output-join",
                "exports": [{
                    "name": "selected_records", "expected_kind": "records", "required": True,
                    "then": {"node_id": "collect-findings", "output": "records"},
                    "else": {"node_id": "saved-records", "output": "records"},
                }],
            },
        },
        publish,
    ]
    return record


class WorkflowSavedOutputFixture(WorkflowPublicationFixture):
    """Source capabilities and file reads on the existing closed workflow fixture."""

    def __init__(self, page):
        super().__init__(page)
        self.publication_sources = copy.deepcopy(SOURCE_CAPABILITIES)
        self.option_overrides = {}
        self.artifact_downloads = []
        self.artifact_bytes = ARTIFACT_BYTES
        for scope in ("user", "group"):
            record = saved_output_workflow_record(scope)
            records = self.group_workflows[GROUP_ID] if scope == "group" else self.personal_workflows
            records[record["id"]] = record
        self.conversations = [{
            "id": ARTIFACT_CONVERSATION_ID, "title": "Saved workflow files",
            "last_updated": "2026-09-18T12:05:00Z",
        }]
        self.messages = {
            ARTIFACT_CONVERSATION_ID: [{
                "id": "saved-output-reply", "conversation_id": ARTIFACT_CONVERSATION_ID,
                "role": "assistant", "content": "Saved workflow output is available.",
                "metadata": {
                    "generated_tabular_outputs": [{
                        "capability": "file_export",
                        "source_kind": "workflow_saved_output",
                        "artifact_message_id": ARTIFACT_MESSAGE_ID,
                        "conversation_id": ARTIFACT_CONVERSATION_ID,
                        "storage_scope": "chat",
                        "output_format": "json",
                        "file_name": ARTIFACT_FILE_NAME,
                        "row_count": 2,
                        "row_source": "saved_records",
                        "summary": "2 exact saved records (valid)",
                    }],
                },
            }],
        }

    def _dispatch(self, route, entry):
        if entry.path in {"/api/user/workflows/editor-options", "/api/group/workflows/editor-options"}:
            assert entry.method == "GET", entry
            shared = entry.path.startswith("/api/group/")
            assert entry.query.get("group_id") == ([GROUP_ID] if shared else None), entry
            options = editor_options("group" if shared else "personal", GROUP_ID if shared else None)
            options.update(
                supported_node_kinds=["task", "if", "route", "for_each", "collect"],
                supported_iterable_kinds=["input", "documents", "workspace_query"],
                supported_query_modes=["all_matches", "best_n"],
                supported_binding_sources=["node_output", "loop_item"],
            )
            options["flow_limits"]["max_loop_items"] = 500
            for runner in [*options["agents"], *options["models"], options["default_model"]]:
                runner["loop_eligible"] = True
            if self.publication_policies is not None:
                options["supported_publication_completion_policies"] = copy.deepcopy(self.publication_policies)
            if self.publication_sources is not None:
                options["publication_source_capabilities"] = copy.deepcopy(self.publication_sources)
            options.update(copy.deepcopy(self.option_overrides))
            self._json(route, options)
        elif entry.path == "/api/v2/orchestration/runs":
            assert entry.method == "GET", entry
            assert entry.query == {"conversation_id": [ARTIFACT_CONVERSATION_ID], "limit": ["25"]}, entry
            self._json(route, {"runs": []})
        elif entry.path == "/api/chat_artifacts/download":
            assert entry.method == "GET", entry
            assert entry.query == {
                "conversation_id": [ARTIFACT_CONVERSATION_ID], "message_id": [ARTIFACT_MESSAGE_ID],
            }, entry
            self.artifact_downloads.append(entry)
            route.fulfill(
                status=200, content_type="application/json", body=self.artifact_bytes,
                headers={"Content-Disposition": f'attachment; filename="{ARTIFACT_FILE_NAME}"'},
            )
        else:
            super()._dispatch(route, entry)


@pytest.fixture
def saved_output_ui(page):
    fixture = WorkflowSavedOutputFixture(page)
    yield fixture
    fixture.assert_clean()
