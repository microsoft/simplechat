# test_orchestration_result_read_amplification.py
"""
Functional tests for bounded, currently authorized retained-result projections.
Version: 0.261.380
Implemented in: 0.261.380

Real result readers, immutable commits, SDK-shaped storage doubles and the
lease-bound store run offline. Counts include nested store execution checks,
not just facade calls or model/provider timing.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from contextvars import Context, copy_context
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from functions_orchestration_result_runtime import read_result_document_citations
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_results import NamedOutput, ResultUnavailableError
from functions_workflow_result_store import AnalysisWorkUnitConflictError, WorkflowResultIntegrityError
from test_orchestration_external_results import ExternalFixture
from test_support.orchestration_results import ResultFixture, complete


def citation_graph(monkeypatch, *, blob, producers=3, diamond=False, chain=False):
    fixture = ResultFixture(blob=blob)
    references = []
    for index in range(producers):
        producer = replace(fixture.producer, step_id=f"producer-{index}")
        fixture.add_producer(producer)
        task = fixture.save(
            producer=producer,
            upstream=(
                tuple(references[-1:]) if chain and index
                else tuple(references[:1]) if diamond and index else ()
            ),
            outputs=[
                NamedOutput("prepared", "structured-v1", {"finding": index}, complete(1)),
                NamedOutput("coverage", "structured-v1", {"citations": [{
                    "document_id": "document-1", "citation_id": "document-1_1", "page_number": 1,
                }]}, complete(1)),
            ],
        )
        references.append(task.output("prepared"))
        if index == 0:
            references.append(task.output("coverage"))
    producer = fixture.consumer()
    answer = fixture.save(
        producer=producer, grounded=False, upstream=tuple(references),
        outputs=[NamedOutput("answer", "markdown-v1", "Draft answer.", complete(1))],
    ).output("answer")
    run = fixture.runs["run-1"]
    run.update(
        run_id="run-1", planner_contract_version=2,
        execution_lease={"token": "server-attempt-token", "claim_id": "claim-1"},
    )
    run["plan"]["planner_contract_version"] = 2
    counts = Counter()

    def check():
        counts["lease"] += 1
        return deepcopy(run)

    def conversation(conversation_id):
        counts["conversation"] += 1
        return deepcopy(fixture.conversation)

    def read_run(run_id):
        counts["producer"] += 1
        return deepcopy(fixture.runs[run_id])

    original_read = fixture.container.read_item

    def read_item(*args, **kwargs):
        counts["container"] += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(fixture.container, "read_item", read_item)
    fixture.service.access.read_conversation = conversation
    fixture.service.access.read_run = read_run
    fixture.service.store = fixture.service.store.for_orchestration_execution(
        "owner", "conversation-1", "run-1",
        guard_token="server-attempt-token", check_execution=check,
    )
    counts.clear()
    return SimpleNamespace(
        fixture=fixture, reference=answer, counts=counts, run=run,
        context=SimpleNamespace(result_service=fixture.service),
    )


@pytest.mark.parametrize("blob", [False, True])
@pytest.mark.parametrize("producers,diamond", [(3, False), (8, True)])
def test_citation_projection_has_a_linear_validation_read_budget(monkeypatch, blob, producers, diamond):
    graph = citation_graph(monkeypatch, blob=blob, producers=producers, diamond=diamond)
    citations = read_result_document_citations(graph.context, graph.reference)
    assert [citation["citation_id"] for citation in citations] == ["document-1_1"]
    baseline = {
        3: {"conversation": 118, "producer": 118, "lease": 777 if blob else 927,
            "container": 418 if blob else 493},
        8: {"conversation": 412, "producer": 412, "lease": 2730 if blob else 3246,
            "container": 1476 if blob else 1734},
    }[producers]
    for kind, original_count in baseline.items():
        assert graph.counts[kind] * 5 <= original_count
    assert graph.counts["conversation"] <= 7 * (producers + 1)
    assert graph.counts["producer"] <= 7 * (producers + 1)
    assert graph.counts["lease"] <= (32 if blob else 40) * (producers + 1)
    assert graph.counts["container"] <= 20 * (producers + 1)


@pytest.mark.parametrize("blob", [False, True])
def test_later_projection_observes_revocation_instead_of_retaining_authority(monkeypatch, blob):
    graph = citation_graph(monkeypatch, blob=blob)
    first = read_result_document_citations(graph.context, graph.reference)
    graph.fixture.conversation["orchestration_deleted"] = True
    with pytest.raises(ResultUnavailableError, match="unavailable"):
        read_result_document_citations(graph.context, graph.reference)
    assert len(first) == 1


@pytest.mark.parametrize("blob", [False, True])
def test_deeper_lineage_stays_within_linear_projection_budgets(monkeypatch, blob):
    graph = citation_graph(monkeypatch, blob=blob, producers=12, chain=True)
    citations = read_result_document_citations(graph.context, graph.reference)
    assert [citation["citation_id"] for citation in citations] == ["document-1_1"]
    assert graph.counts["lease"] <= (32 if blob else 40) * 13
    assert graph.counts["container"] <= 20 * 13
    assert graph.counts["conversation"] <= 7 * 13
    assert graph.counts["producer"] <= 7 * 13


@pytest.mark.parametrize("blob", [False, True])
@pytest.mark.parametrize("during_exit", [False, True])
@pytest.mark.parametrize("change", [
    "conversation", "owner", "attempt", "checkpoint", "disabled", "claim",
])
def test_scope_rechecks_mutable_authority_even_during_final_manifest_reads(
    monkeypatch, blob, during_exit, change,
):
    graph = citation_graph(monkeypatch, blob=blob)
    service = graph.fixture.service

    def revoke():
        if change == "conversation":
            graph.fixture.conversation["orchestration_deleted"] = True
        elif change == "owner":
            graph.run["user_id"] = "foreign-owner"
        elif change == "attempt":
            graph.run["attempt_index"] = graph.reference.producer.attempt_index + 1
        elif change == "checkpoint":
            graph.run["checkpoints_deleted"] = True
        elif change == "disabled":
            for step in graph.run["plan"]["steps"]:
                step["enabled"] = False
        elif change == "claim":
            graph.run["execution_lease"]["claim_id"] = "replacement-claim"

    original = service.store.load_committed_orchestration_result
    loads = Counter()

    def load(*args, **kwargs):
        loads[args] += 1
        if during_exit and loads[args] == 2:
            revoke()
        return original(*args, **kwargs)

    monkeypatch.setattr(service.store, "load_committed_orchestration_result", load)
    with pytest.raises((ResultUnavailableError, AnalysisWorkUnitConflictError)):
        with service.read_operation():
            reader = service.open_result(graph.reference)
            value = reader.read_text()
            assert value == "Draft answer."
            if not during_exit:
                revoke()
    assert service._read_operation.get() is None
    assert service.access._read_operation.get() is None


@pytest.mark.parametrize("blob", [False, True])
def test_scopes_discard_failed_state_and_do_not_outlive_their_readers(monkeypatch, blob):
    graph = citation_graph(monkeypatch, blob=blob)
    service = graph.fixture.service
    with pytest.raises(RuntimeError, match="projection_failed"):
        with service.read_operation():
            reader = service.open_result(graph.reference)
            value = reader.read_text()
            assert value == "Draft answer."
            raise RuntimeError("projection_failed")
    assert service._read_operation.get() is None
    assert service.access._read_operation.get() is None
    with service.read_operation():
        value = reader.read_text()
    assert value == "Draft answer."
    graph.fixture.conversation["orchestration_deleted"] = True
    with pytest.raises(ResultUnavailableError):
        reader.read_text()


def test_independent_context_cannot_inherit_another_operations_authority(monkeypatch):
    graph = citation_graph(monkeypatch, blob=False)
    service = graph.fixture.service
    with service.read_operation():
        reader = service.open_result(graph.reference)
        value = reader.read_text()
        graph.fixture.conversation["orchestration_deleted"] = True
        with pytest.raises(ResultUnavailableError):
            Context().run(reader.read_text)
        graph.fixture.conversation.pop("orchestration_deleted")
    assert value == "Draft answer."


@pytest.mark.parametrize("during_scope", [False, True])
def test_copied_context_cannot_reuse_completed_or_other_thread_authority(monkeypatch, during_scope):
    graph = citation_graph(monkeypatch, blob=False)
    service = graph.fixture.service
    with service.read_operation():
        reader = service.open_result(graph.reference)
        context = copy_context()
        if during_scope:
            graph.fixture.conversation["orchestration_deleted"] = True
            with ThreadPoolExecutor(max_workers=1) as worker:
                future = worker.submit(context.run, reader.read_text)
                with pytest.raises(ResultUnavailableError):
                    future.result()
            graph.fixture.conversation.pop("orchestration_deleted")
    graph.fixture.conversation["orchestration_deleted"] = True
    with pytest.raises(ResultUnavailableError):
        context.run(reader.read_text)


def test_nested_scopes_share_work_but_do_not_allow_writes_or_forged_descriptors(monkeypatch):
    graph = citation_graph(monkeypatch, blob=False)
    service = graph.fixture.service
    with service.read_operation():
        reader = service.open_result(graph.reference)
        value = reader.read_text()
        before = dict(graph.counts)
        with service.read_operation():
            same = reader.read_text()
        assert graph.counts["container"] > before["container"]
        assert graph.counts["conversation"] == before["conversation"]
        with pytest.raises(ResultContractError) as forged:
            service.open_result(replace(graph.reference, content_sha256="a" * 64))
        assert forged.value.code == "result_reference_mismatch"
        writes = graph.fixture.container.sequence
        with pytest.raises(ResultContractError) as write:
            graph.fixture.save()
        assert write.value.code == "result_read_only"
        assert graph.fixture.container.sequence == writes
    assert value == same == "Draft answer."


def test_cancellation_keeps_retained_inputs_readable_but_write_authority_fresh(monkeypatch):
    graph = citation_graph(monkeypatch, blob=False)
    service = graph.fixture.service
    with service.read_operation():
        reader = service.open_result(graph.reference)
        graph.run["cancellation_requested_at"] = "2026-05-21T00:00:00Z"
        value = reader.read_text()
        with pytest.raises(ResultUnavailableError) as stopped:
            service.access.authorize_producer(graph.reference.producer, for_write=True)
        assert stopped.value.code == "result_attempt_stopped"
    assert value == "Draft answer."


@pytest.mark.parametrize("source_type", ["agent", "action"])
def test_current_external_authority_is_revalidated_at_scope_exit(source_type):
    fixture = ExternalFixture(source_type)
    task = fixture.retain()
    with pytest.raises(PermissionError):
        with fixture.service.read_operation():
            reader = fixture.service.open_result(task.output("knowledge"))
            value = reader.read_value()
            fixture.enabled.clear()
    assert value["findings"] == ["Retained first finding.", "Retained final finding."]


@pytest.mark.parametrize("require_current", [False, True])
def test_reuse_keeps_snapshot_and_current_external_policies_distinct(require_current):
    fixture = ExternalFixture("action")
    task = fixture.retain(source_policy="snapshot")
    outcome = pytest.raises(ResultUnavailableError) if require_current else nullcontext()
    with outcome:
        with fixture.service.read_operation():
            relaxed = fixture.service.open_result(task.output("knowledge"))
            value = relaxed.read_value()
            strict = fixture.service.open_result(
                task.output("knowledge"), require_current_sources=require_current,
            )
            strict_value = strict.read_value()
            identity, reference = next(iter(fixture.current.items()))
            fixture.current[identity] = replace(reference, source_revision="replacement-revision")
    assert value == strict_value


@pytest.mark.parametrize("blob", [False, True])
def test_scope_reloads_committed_integrity_instead_of_trusting_cached_manifests(monkeypatch, blob):
    graph = citation_graph(monkeypatch, blob=blob)
    service = graph.fixture.service
    original = service.store.load_committed_orchestration_result
    loads = Counter()

    def load(*args, **kwargs):
        loads[args] += 1
        if loads[args] == 2:
            raise WorkflowResultIntegrityError("result_integrity_failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(service.store, "load_committed_orchestration_result", load)
    with pytest.raises(WorkflowResultIntegrityError):
        with service.read_operation():
            reader = service.open_result(graph.reference)
            value = reader.read_text()
            assert value == "Draft answer."
    assert service._read_operation.get() is None
    monkeypatch.setattr(service.store, "load_committed_orchestration_result", original)
    with service.read_operation():
        value = reader.read_text()
    assert value == "Draft answer."
