# workflow_result_chat.py
"""
Shared fixtures for the workflow-results-in-chat functional tests.
Version: 0.261.214
Implemented in: 0.261.214

Fake Cosmos containers that honour a query's projection, an in-memory result store
that keeps canonical ASCII JSON like the real byte transport, a source resolver, and
a personal workflow run built through the real result contract.
"""

import hashlib
import json
import re
from copy import deepcopy

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError

import functions_workflow_result_reader as reader
from functions_analysis_access import build_analysis_access
from functions_workflow_results import (
    build_workflow_task_result,
    load_workflow_task_input,
    persist_workflow_task_result,
    workflow_result_summary,
)


USER = "user-owner-1"
OTHER_USER = "user-other-2"
WORKFLOW_ID = "wf-digest-3c1"
RUN_ID = "run-digest-9a7"
COMPLETED_AT = "2026-01-05T14:02:00+00:00"
SOURCE = {
    "document_id": "doc-source-1", "scope_type": "group", "scope_id": "group-source",
    "source_version": "1", "content_sha256": "a" * 64,
}
SECOND_SOURCE = {**SOURCE, "document_id": "doc-source-2"}
EXPECTED_QUERY = (
    "SELECT c.workflow_id, c.run_id, c.task_id, c.task_order, c.status, c.item_type, c.label, "
    "c.workflow_result FROM c "
    "WHERE c.run_id = @run_id AND c.workflow_id = @workflow_id AND c.item_type = 'task'"
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class CanonicalStore:
    """Stores canonical ASCII JSON by digest, like the real result store's byte transport."""

    def __init__(self):
        self.contents = {}
        self.loads = []
        self.pages = []
        self.load_error = None

    def save(self, workflow, run_id, task_id, data, **kwargs):
        content = canonical(data)
        digest = hashlib.sha256(content.encode("ascii")).hexdigest()
        self.contents[digest] = content
        return {"sha256": digest, "size_bytes": len(content)}

    def load(self, workflow, run_id, task_id, reference, **selectors):
        if self.load_error is not None:
            raise self.load_error
        self.loads.append(reference["sha256"])
        if reference["sha256"] not in self.contents:
            raise CosmosResourceNotFoundError(status_code=404, message="missing")
        return json.loads(self.contents[reference["sha256"]])

    def read_page(self, workflow, run_id, task_id, reference, *, offset=0, limit=65536):
        self.pages.append((reference["sha256"], offset, limit))
        content = self.contents[reference["sha256"]]
        end = min(offset + limit, len(content))
        return {
            "content": content[offset:end], "offset": offset,
            "next_offset": end if end < len(content) else None,
            "total_bytes": len(content), "complete": end == len(content),
        }


def projected_fields(query):
    selected = re.match(r"SELECT (.*?) FROM c ", query).group(1)
    return [field.strip()[2:] for field in selected.split(",")]


class FakeContainer:
    """Point reads by id and partition; queries honour the projection they are given."""

    def __init__(self, documents, *, partition):
        self.documents = documents
        self.partition = partition
        self.read_error = None
        self.query_error = None
        self.iteration_error = None
        self.reads = []
        self.queries = []

    def read_item(self, item, partition_key):
        self.reads.append((item, partition_key))
        if self.read_error is not None:
            raise self.read_error
        for document in self.documents:
            if document.get("id") == item and document.get(self.partition) == partition_key:
                return {**deepcopy(document), "_etag": "etag-1", "_ts": 1}
        raise CosmosResourceNotFoundError(status_code=404, message="missing")

    def query_items(self, query, parameters, partition_key):
        self.queries.append({"query": query, "parameters": deepcopy(parameters), "partition_key": partition_key})
        if self.query_error is not None:
            raise self.query_error
        values = {parameter["name"]: parameter["value"] for parameter in parameters}
        fields = projected_fields(query)
        rows = [
            {field: deepcopy(document[field]) for field in fields if field in document}
            for document in self.documents
            if document.get("run_id") == partition_key == values.get("@run_id")
            and document.get("workflow_id") == values.get("@workflow_id")
            and document.get("item_type") == "task"
        ]

        def iterate():
            for index, row in enumerate(rows):
                if self.iteration_error is not None and index == 1:
                    raise self.iteration_error
                yield row

        return iterate()


class Sources:
    def __init__(self):
        self.allowed = True
        self.readers = []

    def __call__(self, ids, **kwargs):
        self.readers.append(kwargs.get("user_id"))
        return [{
            "document_id": identifier, "scope": "group", "scope_id": "group-source", "source_version": "1",
            "authorization_status": "authorized" if self.allowed else "unresolved",
        } for identifier in ids]


class RunFixture:
    def __init__(self, *, status="completed", name="Weekly digest"):
        self.store = CanonicalStore()
        self.sources = Sources()
        self.workflow = {"id": WORKFLOW_ID, "user_id": USER, "name": name, "type": "personal_workflow"}
        self.run = {
            "id": RUN_ID, "workflow_id": WORKFLOW_ID, "user_id": USER, "status": status,
            "completed_at": COMPLETED_AT, "workflow_name": name, "response_preview": "RUN-PREVIEW-TEXT",
        }
        self.items = []
        self.containers = {
            "workflows": FakeContainer([self.workflow], partition="user_id"),
            "runs": FakeContainer([self.run], partition="user_id"),
            "run_items": FakeContainer(self.items, partition="run_id"),
        }

    def add_task(self, task_id, result, *, order, status="succeeded", label=None, consumed=None, edit=None):
        envelope = build_workflow_task_result(result, workflow=self.workflow, run_id=RUN_ID, task={"id": task_id})
        if consumed is not None:
            envelope["consumed_inputs"] = consumed
        if edit is not None:
            edit(envelope)
        manifest, reference = persist_workflow_task_result(
            envelope, workflow=self.workflow, run_id=RUN_ID, task_id=task_id, save_result=self.store.save,
        )
        item = {
            "id": f"{RUN_ID}:{task_id}", "type": "workflow_run_item", "item_type": "task", "run_id": RUN_ID,
            "user_id": USER, "workflow_id": WORKFLOW_ID, "group_id": None, "workflow_name": self.workflow["name"],
            "task_id": task_id, "task_order": order, "label": label or f"Step {order}", "status": status,
            "output_preview": "ITEM-PREVIEW-TEXT", "workflow_result": workflow_result_summary(manifest, reference),
        }
        self.items[:] = [existing for existing in self.items if existing["task_id"] != task_id] + [item]
        return manifest, reference

    def receipt(self, task_id, reference, *, allow_partial=False):
        _, consumed = load_workflow_task_input(
            self.workflow, RUN_ID, task_id, reference, load_result=self.store.load, source_resolver=self.sources,
            allow_partial=allow_partial,
        )
        return consumed

    def read(self, user_id=USER, workflow_id=WORKFLOW_ID, run_id=RUN_ID, **options):
        arguments = {
            "containers": self.containers, "load_result": self.store.load,
            "read_page": self.store.read_page, "source_resolver": self.sources,
        }
        arguments.update(options)
        return reader.read_workflow_result(user_id, workflow_id, run_id, **arguments)

    def reset_counters(self):
        self.store.loads.clear()
        self.store.pages.clear()
        self.sources.readers.clear()


def analysis_result(records=None, *, sources=(SOURCE,), reply="The analysis found one finding."):
    return {
        "reply": reply,
        "authoritative_result": {"kind": "records", "value": records or [{"finding": "Needs an owner."}]},
        "analysis_access": build_analysis_access(list(sources)),
    }


def accepted_partial(envelope):
    envelope["workflow_validation"] = {
        "version": 1, "status": "accepted_partial", "eligible": True,
        "reason_codes": ["producer_coverage_incomplete"], "counts": {"accepted": 1},
    }


def closed(call):
    with pytest.raises(reader.WorkflowResultUnavailable) as caught:
        call()
    return caught.value


def two_text_tasks(fixture):
    fixture.add_task("task-collect-71", {"reply": "Collected three headlines."}, order=1, label="Collect news")
    fixture.add_task("task-summary-72", {"reply": "The digest: markets rose."}, order=2, label="Write the digest")
