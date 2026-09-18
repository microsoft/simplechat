# functions_m365_workflow_checkpoints.py
"""Complete workflow task results retained independently from model context."""

import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from functions_conversation_memory import EvidenceChunk, EvidenceSource
from functions_m365_execution import get_m365_execution_context, m365_execution_context
from functions_m365_approvals import M365PolicyError


_dependencies = {}


def configure_m365_workflow_checkpoints(*, memory_resolver, jobs_factory):
    _dependencies.update(memory_resolver=memory_resolver, jobs_factory=jobs_factory)


@contextmanager
def m365_workflow_task_context(task_id):
    context = get_m365_execution_context()
    if context is None:
        yield
        return
    with m365_execution_context(replace(context, step_id=task_id)):
        yield


def read_m365_task_checkpoint(task_id):
    context = get_m365_execution_context()
    if context is None or not context.workflow_id or not _dependencies:
        return None
    jobs = _dependencies["jobs_factory"]()
    try:
        record = jobs.read_item(context.request_id, partition_key=context.data_user_id)
    except CosmosResourceNotFoundError:
        return None
    entry = (record.get("task_checkpoints") or {}).get(task_id)
    if not entry:
        return None
    if entry["workflow_fingerprint"] != context.workflow_fingerprint:
        raise M365PolicyError("m365_workflow_changed", "The workflow changed after this task completed.")
    store, memory_context = _dependencies["memory_resolver"](context)
    parts = []
    start = 0
    while start is not None:
        page = store.read_evidence_range(
            memory_context, entry["run_id"], entry["evidence_id"], start=start,
        )
        parts.extend(chunk["text"] for chunk in page["chunks"])
        start = page["next_start"]
    return json.loads("".join(parts))


def save_m365_task_checkpoint(task_id, task_result):
    context = get_m365_execution_context()
    if context is None or not context.workflow_id:
        return
    if not _dependencies:
        raise M365PolicyError("m365_checkpoint_unavailable", "Workflow task checkpoints are not configured.")
    jobs = _dependencies["jobs_factory"]()
    record = jobs.read_item(context.request_id, partition_key=context.data_user_id)
    store, memory_context = _dependencies["memory_resolver"](context)
    serialized = json.dumps(task_result, sort_keys=True, ensure_ascii=False, default=str)
    run = store.create_run(
        memory_context, request_id=context.request_id, purpose="m365_workflow_task",
    )
    source = store.add_evidence(
        memory_context, run["run_id"],
        source=EvidenceSource(
            source_type="workflow_checkpoint", source_id=task_id,
            version=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            coverage_complete=True,
        ),
        chunks=(
            EvidenceChunk(serialized[offset:offset + 24000])
            for offset in range(0, len(serialized), 24000)
        ),
    )
    store.complete_run(memory_context, run["run_id"])
    updated = {
        **record,
        "task_checkpoints": {
            **record.get("task_checkpoints", {}),
            task_id: {
                "run_id": run["run_id"], "evidence_id": source["evidence_id"],
                "workflow_fingerprint": context.workflow_fingerprint,
            },
        },
    }
    jobs.replace_item(
        record["id"], body=updated,
        etag=record["_etag"], match_condition=MatchConditions.IfNotModified,
    )
