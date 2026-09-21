# orchestration_results.py
"""
External-I/O doubles and exact foundation fixtures.
Version: 0.261.125
Implemented in: 0.261.125
"""

from copy import deepcopy
from dataclasses import replace

from functions_orchestration_result_contracts import Completeness, Coverage, ProducerIdentity, RecordColumn
from functions_orchestration_results import NamedOutput, OrchestrationResultAccess, OrchestrationResults
from functions_workflow_result_store import WorkflowResultStore
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_workflow_result_store import FakeBlobService


COLUMNS = (
    RecordColumn("id", "string"),
    RecordColumn("amount", "number", nullable=True),
    RecordColumn("enabled", "boolean"),
    RecordColumn("detail", "json", nullable=True),
)
ROWS = [
    {"id": "001", "amount": 0, "enabled": False, "detail": {"text": "first\nline", "nested": [None, True]}},
    {"id": "=SUM(A1:A2)", "amount": 1.25, "enabled": True, "detail": "\u4e2d\u6587 caf\u00e9"},
    {"id": "last", "amount": None, "enabled": False, "detail": ["last", {"value": 7}]},
]
SOURCE_FREE_VALUE = {"version": 1, "id": "007", "enabled": False, "nullable": None, "values": [1, "1", True]}
TABULAR_FOREGROUND = {"status": "completed", "kind": "records", "value": ROWS, "source_row_count": 3}
TABULAR_DURABLE = {"status": "running", "run_id": "native-job-1"}


def source(document_id="document-1"):
    return {
        "document_id": document_id, "scope": "personal", "scope_id": "owner",
        "source_version": 1, "source_revision": "revision-1",
    }


def complete(count, *, status="complete", expected=None):
    return Completeness(
        status, count if expected is None else expected, count,
        Coverage(1, 1 if status == "complete" else 0, "work_units"),
        {"complete": "valid", "partial": "partial", "invalid": "invalid", "pending": "pending"}.get(status, "not_validated"),
        ("producer_schema",), () if status == "complete" else ("Only the retained subset is available.",),
    )


def native_analysis(count=3):
    return {
        "analysis_result_version": "analyze-final-v1",
        "analysis_reply": "Complete narrative findings, not a published report.",
        "source_manifest": [{**source(), "authorization_status": "authorized"}],
        "authoritative_result": {"kind": "records", "value": [
            {
                "record_id": f"record-{index}", "document_id": "document-1",
                "values": {"finding": f"Complete finding {index}", "detail": "retained detail " * 30},
                "evidence_refs": [f"evidence-{index}"],
            } for index in range(count)
        ]},
        "analysis_evidence": [
            {"evidence_id": f"evidence-{index}", "document_id": "document-1", "quote": f"Source quote {index}"}
            for index in range(count)
        ],
        "analysis_validation": {"status": "valid", "checks": ["record_shape"], "limitations": []},
        "coverage": {"documents": [{"document_id": "document-1", "total_windows": 1, "processed_windows": 1}]},
    }


class ResultContainer(AtomicMemoryContainer):
    """Reuse the transactional fake with the shared result store's cleanup queries."""

    def __init__(self):
        super().__init__("run_id")

    def delete_item(self, item, partition_key, **kwargs):
        if "etag" not in kwargs:
            kwargs["etag"] = self.read_item(item, partition_key)["_etag"]
        return super().delete_item(item, partition_key, **kwargs)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        if "@record_type" not in query:
            return super().query_items(query, parameters, partition_key, **kwargs)
        values = {entry["name"][1:]: entry["value"] for entry in parameters}
        self.queries.append((query, deepcopy(parameters), partition_key))
        return [
            deepcopy(row) for (partition, _), row in self.items.items()
            if (partition_key is None or partition == partition_key)
            and all(
                row.get(name) == value for name, value in values.items() if name != "record_type"
            )
            and row.get("type") == values["record_type"] and row.get("item_type") == values["record_type"]
        ]


class ResultFixture:
    def __init__(self, *, blob=False, max_bytes=32 * 1024 * 1024):
        self.container = ResultContainer()
        self.blobs = FakeBlobService() if blob else None
        self.max_bytes = max_bytes
        self.conversation = {"id": "conversation-1", "user_id": "owner"}
        self.runs = {}
        self.sources = {"document-1": source()}
        self.held = set()
        self.denied = set()
        self.source_reads = []
        self.producer = ProducerIdentity("owner", "conversation-1", "run-1", 1, "analyze", "document_analyze", "analyze-final-v1")
        self.add_producer(self.producer)
        self.service = self.restart()

    def add_producer(self, producer):
        run = self.runs.setdefault(producer.run_id, {
            "id": producer.run_id, "user_id": producer.user_id, "conversation_id": producer.conversation_id,
            "attempt_index": producer.attempt_index, "status": "running", "plan": {"steps": []},
        })
        run["plan"]["steps"].append({
            "step_id": producer.step_id, "capability_id": producer.capability_id, "enabled": True,
        })

    def consumer(self, **changes):
        producer = replace(self.producer, step_id="consume", capability_id="compose", contract_version="compose-v1", **changes)
        self.add_producer(producer)
        return producer

    def resolve(self, ids, **scope):
        self.source_reads.append((list(ids), deepcopy(scope)))
        return [
            {
                **deepcopy(self.sources.get(document_id) or source(document_id)),
                "authorization_status": "authorized" if document_id in self.sources and document_id not in self.denied else "unresolved",
            }
            for document_id in ids
        ]

    def metadata(self, document_id, user_id, group_id=None, public_workspace_id=None):
        if user_id != "owner" or document_id not in self.sources or document_id in self.denied:
            raise PermissionError("Fixture source access denied.")
        snapshot = self.sources[document_id]
        if group_id != (snapshot["scope_id"] if snapshot["scope"] == "group" else None):
            raise PermissionError("Fixture group access denied.")
        if public_workspace_id != (snapshot["scope_id"] if snapshot["scope"] == "public" else None):
            raise PermissionError("Fixture public workspace access denied.")
        document = {"id": document_id, "user_id": user_id, "version": snapshot["source_version"]}
        if document_id in self.held:
            document["content_screening"] = {"state": "pending_review"}
        return document

    def restart(self, *, blobs=True):
        store = WorkflowResultStore(
            self.container, self.blobs if blobs else None, "private-results",
            max_size_bytes=self.max_bytes,
        )
        access = OrchestrationResultAccess(
            user_id="owner", conversation_id="conversation-1",
            read_conversation=lambda conversation_id: deepcopy(self.conversation),
            read_run=lambda run_id: deepcopy(self.runs.get(run_id)),
            source_resolver=self.resolve, source_metadata_reader=self.metadata,
        )
        return OrchestrationResults(store, access)

    def save(self, *, outputs=None, producer=None, status="complete", grounded=True, **kwargs):
        return self.service.persist_task_result(
            producer=producer or self.producer, role="reason", status=status,
            outputs=outputs if outputs is not None else [NamedOutput("findings", "records-v1", deepcopy(ROWS), complete(3), COLUMNS)],
            sources=[source()] if grounded else [], origin="grounded" if grounded or kwargs.get("upstream") else "generated",
            guard_token="server-attempt-token", **kwargs,
        )
