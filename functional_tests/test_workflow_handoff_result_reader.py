#!/usr/bin/env python3
# test_workflow_handoff_result_reader.py
"""
Functional test for reading a one-time hand-off's report in the workflow result reader.
Version: 0.261.252
Implemented in: 0.261.250 (the report's lineage re-proof: 0.261.252)

This test ensures that the result reader, which keeps structured (v3) runs closed, opens exactly
one shape: a one-time chat hand-off run whose single workflow output is the report node's text.

* The run must come from chat orchestration, its workflow must be the hand-off's one-time
  workflow under the deterministic id, and its one receipt must name the report node, its text
  output and a well-formed reference. Every other structured shape stays closed with no read.
* The report is read through its exact node selectors and bound to a digest. An edited or
  re-enabled definition fails closed before any load.
* Before the result is described or excerpted, the shared node lineage authorizer re-proves the
  report's lineage against the saved flow: every consumed-input receipt must chain to a real
  parent result of this run. A malformed receipt, a missing parent or a corrupt parent closes
  the read, and the report's text is never loaded.
* Excerpts stay bounded, carry no store references or ids, and page a large report once.

It uses fake containers and an in-memory canonical result store; the hand-off builder, the result
contract, the node identity, the lineage authorizer and the reader are real. Checks use explicit
raises, so they hold under ``python -O``.
"""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_workflow_result_reader as reader  # noqa: E402
from functions_workflow_execution import workflow_execution_scope  # noqa: E402
from functions_workflow_handoff_builder import build_handoff_definition  # noqa: E402
from functions_workflow_identity import workflow_execution_id, workflow_node_identity  # noqa: E402
from functions_workflow_node_results import open_workflow_record_input, result_selectors  # noqa: E402
# _verify_payload is the real store's size and digest check; _build_task_result is how the
# structured runner builds an engine node's (collect's) result, which has no task.
from functions_workflow_result_store import MAX_PAGE_BYTES, _verify_payload  # noqa: E402
from functions_workflow_results import (  # noqa: E402
    _build_task_result,
    build_workflow_task_result,
    persist_workflow_task_result,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_result_chat import (  # noqa: E402
    USER,
    CanonicalStore,
    FakeContainer,
    RunFixture,
    accepted_partial,
    analysis_result,
    canonical,
    closed,
)


MINIMUM_VERSION = "0.261.250"
LINEAGE_VERSION = "0.261.252"
HANDOFF_ID = "handoff-7f3"
RUN = "run-handoff-41"
CONVERSATION = "conversation-9"
COMPLETED_AT = "2026-01-05T14:02:00+00:00"
REQUESTED_AT = "2026-01-05T13:00:00+00:00"
REPORT_TEXT = "The review found two contracts that need an owner."
COLLECTED = [{"finding": "Contract A needs an owner."}, {"finding": "Contract B needs an owner."}]
WID = reader._handoff_workflow_id(USER, HANDOFF_ID)
DEFAULT_BUDGET = reader.DEFAULT_EXCERPT_BUDGET_BYTES
UNAVAILABLE = "[WorkflowResults] Workflow result unavailable"


def _require(condition, message):
    """Fail even under ``python -O``, which removes assert statements."""
    if not condition:
        raise AssertionError(message)


def _same(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _derived_id(workflow_id, kind, key):
    return f"{workflow_id}-{kind}-{key}"


class ReportExecution:
    """The admitted report node, as the structured runner exposes it to its task."""

    def __init__(self, workflow, run_id, task_id):
        self.node = {"id": "report-node", "kind": "task", "task_id": task_id}
        self.iteration_inputs = {}
        self._execution_id = workflow_execution_id(workflow, run_id, "report-node")

    def selectors(self, *, attempt=None):
        return {
            "execution_id": self._execution_id, "node_id": "report-node",
            "iteration_path": [], "attempt": attempt or 1,
        }


class NodeStore(CanonicalStore):
    """The canonical store, also recording the exact node selectors every read passes."""

    def __init__(self):
        super().__init__()
        self.selectors = []

    def load(self, workflow, run_id, task_id, reference, **selectors):
        self.selectors.append(("load", reference["sha256"], deepcopy(selectors)))
        return super().load(workflow, run_id, task_id, reference)

    def read_page(self, workflow, run_id, task_id, reference, *, offset=0, limit=65536, **selectors):
        self.selectors.append(("page", reference["sha256"], deepcopy(selectors)))
        return super().read_page(workflow, run_id, task_id, reference, offset=offset, limit=limit)


class HandoffFixture:
    """A finished hand-off run whose report was saved through the real v3 result contract.

    ``lineage``, when given, saves the report's parents and returns its consumed-input receipts. It
    gets only the saved workflow and the store, so no hook runs on a half-built fixture. Without it
    the report consumed nothing, so there's no lineage to walk.
    """

    def __init__(self, *, status="completed", title="Board summary", result=None, partial=False, lineage=None):
        self.store = NodeStore()
        blueprint = {
            "name": "Contract review",
            "loop": {"source": "documents", "documents": ["doc-a"]},
            "tasks": [
                {"title": "Review one", "instructions": "Review it."},
                {"title": title, "instructions": "Write the report."},
            ],
        }
        handles = {
            "documents": {"doc-a": {"document_id": "doc-1", "scope_type": "personal", "scope_id": USER}},
            "scopes": {},
            "agents": {},
        }
        workflow = build_handoff_definition(
            blueprint, handles, workflow_id=WID, max_items=1, derived_id=_derived_id,
            alert_fields=lambda alerts, workflow_id: {"alert_mode": "rules"},
        )
        workflow.update({
            "id": WID, "user_id": USER, "type": "personal_workflow",
            "origin": {
                "source": "orchestration", "conversation_id": CONVERSATION,
                "orchestration_run_id": "orchestration-run-1", "proposal_id": HANDOFF_ID,
                "created_at": REQUESTED_AT, "edited": False, "one_time": True,
            },
        })
        self.workflow = workflow
        self.task = workflow["tasks"][1]
        self.task_id = self.task["id"]
        with workflow_execution_scope(ReportExecution(workflow, RUN, self.task_id)):
            envelope = build_workflow_task_result(
                result or {"reply": REPORT_TEXT}, workflow=workflow, run_id=RUN, task=self.task,
            )
        envelope["workflow_validation"] = {"version": 1, "status": "valid", "eligible": True}
        if partial:
            accepted_partial(envelope)
        if lineage is not None:
            envelope["consumed_inputs"] = lineage(workflow, self.store)
        self.manifest, self.reference = persist_workflow_task_result(
            envelope, workflow=workflow, run_id=RUN, task_id=self.task_id, save_result=self.store.save,
        )
        self.text_reference = dict(self.manifest["outputs"]["text"]["result_ref"])
        self.selectors = {
            key: deepcopy(self.manifest["identity"][key])
            for key in ("node_id", "execution_id", "iteration_path", "attempt")
        }
        self.run = {
            "id": RUN, "workflow_id": WID, "user_id": USER, "status": status,
            "completed_at": COMPLETED_AT, "workflow_name": "Contract review",
            "trigger_source": "chat_orchestration", "definition_version": 3,
            "chat_invocation": {
                "version": 1, "source": "chat_orchestration", "conversation_id": CONVERSATION,
                "user_message_id": "message-1", "orchestration_run_id": "orchestration-run-1",
                "attempt_root_run_id": "orchestration-run-1", "step_id": "step-1",
                "requested_by": USER, "requested_at": REQUESTED_AT, "handoff_id": HANDOFF_ID,
            },
            # The flow runner's metadata-only receipt for the workflow's one output.
            "workflow_outputs": [{
                "producer": deepcopy(self.manifest["identity"]), "result_ref": dict(self.reference),
                "output_name": "text", "output_ref": dict(self.text_reference), "input_name": "report",
            }],
        }
        self.containers = {
            "workflows": FakeContainer([self.workflow], partition="user_id"),
            "runs": FakeContainer([self.run], partition="user_id"),
            "run_items": FakeContainer([], partition="run_id"),
        }

    @property
    def receipt(self):
        return self.run["workflow_outputs"][0]

    def reset(self):
        self.store.loads.clear()
        self.store.pages.clear()
        self.store.selectors.clear()

    def read(self, workflow_id=WID, **options):
        arguments = {
            "containers": self.containers, "load_result": self.store.load, "read_page": self.store.read_page,
        }
        arguments.update(options)
        return reader.read_workflow_result(USER, workflow_id, RUN, **arguments)

    def digest(self, status="completed"):
        return reader.workflow_result_digest(WID, RUN, status, [{
            "task_id": self.task_id,
            "workflow_result": {"authoritative_output": "text", "result_ref": self.reference},
        }])


class CollectedParent:
    """The report's ``collect`` parent: a real records result, saved the way the runner saves it.

    The collect node is an engine node with no task, so its result is built the way the runner
    builds a control node's result and saved through the real v2 contract. The report's receipt
    is the one the runner records for a records input: the real record reader proves the parent
    and names the exact output, and the runner adds the input name. ``tamper``, when given, may
    then change the receipt; it gets the parent's manifest and a way to save another parent.
    """

    def __init__(self, tamper=None):
        self.tamper = tamper
        self.identity = self.manifest = self.reference = None

    def receipts(self, workflow, store):
        identity = workflow_node_identity(workflow, RUN, "collect", workflow_execution_id(workflow, RUN, "collect"), 1)
        collected = _build_task_result({
            "reply": "Collected two findings.",
            "authoritative_result": {"kind": "records", "value": deepcopy(COLLECTED)},
        }, identity, "workflow-result-v2")
        collected["consumed_inputs"] = []
        collected["workflow_validation"] = {"version": 1, "status": "valid", "eligible": True}
        self.identity = identity
        self.manifest, self.reference = persist_workflow_task_result(
            collected, workflow=workflow, run_id=RUN, task_id=None, save_result=store.save,
        )
        records = open_workflow_record_input(
            workflow, RUN, identity, self.reference, output_name="records",
            reader_user_id=USER, load_result=store.load,
        )
        receipt = {**records.receipt, "input_name": "findings"}
        if self.tamper is not None:
            self.tamper(receipt, self.manifest, lambda parent: store.save(workflow, RUN, None, parent))
        return [receipt]


class LineageFixture(HandoffFixture):
    """A hand-off whose report consumed a real ``collect`` result, through the runner's contract."""

    def __init__(self, *, tamper=None, **options):
        parent = CollectedParent(tamper)
        super().__init__(lineage=parent.receipts, **options)
        self.collect_identity = parent.identity
        self.collect_manifest = parent.manifest
        self.collect_reference = parent.reference
        self.reset()


def _repoint(fixture, manifest):
    """Save an edited report manifest under its own valid hash and point the run's receipt at it."""
    reference = fixture.store.save(fixture.workflow, RUN, fixture.task_id, manifest)
    fixture.receipt["result_ref"] = reference
    return reference


def _digest_for(fixture, reference, status="completed"):
    return reader.workflow_result_digest(WID, RUN, status, [{
        "task_id": fixture.task_id, "workflow_result": {"authoritative_output": "text", "result_ref": reference},
    }])


def _closed_stages(monkeypatch):
    """Record the reader's closed-reason log entries, which name the stage that closed the read."""
    logged = []

    def record(message, extra=None, **kwargs):
        if message == UNAVAILABLE:
            logged.append(dict(extra or {}))

    monkeypatch.setattr(reader, "log_event", record)
    return logged


def _verifying(store):
    """The canonical store's loader with the real result store's size and digest check."""
    def load(workflow, run_id, task_id, reference, **selectors):
        value = store.load(workflow, run_id, task_id, reference, **selectors)
        _verify_payload(store.contents[reference["sha256"]].encode("ascii"), reference)
        return value

    return load


def _refused(fixture, code, **options):
    error = closed(lambda: fixture.read(**options))
    _same(error.code, code, "the closed reason")
    return error


def _unread(fixture, label):
    _same(fixture.store.loads, [], f"{label}: manifest or section loads")
    _same(fixture.store.pages, [], f"{label}: page reads")


def test_version_is_at_least_the_handoff_release():
    assert_app_version_at_least(MINIMUM_VERSION)


def test_version_is_at_least_the_lineage_release():
    assert_app_version_at_least(LINEAGE_VERSION)


def test_the_handoff_workflow_id_matches_the_draft_service():
    # functions_workflow_drafts.orchestration_workflow_id("owner-1", "handoff-1"), pinned by the builder test.
    _same(reader._handoff_workflow_id("owner-1", "handoff-1"), "481a936e-5e1d-5cc8-a4c9-d8165ded91bf", "the id")
    _same(reader._handoff_workflow_id(" owner-1 ", " handoff-1 "), "481a936e-5e1d-5cc8-a4c9-d8165ded91bf", "padded")
    for user_id, handoff_id in (("", "handoff-1"), ("owner-1", "  "), (None, "handoff-1"), ("owner-1", None)):
        _require(reader._handoff_workflow_id(user_id, handoff_id) is None, f"{user_id!r}, {handoff_id!r} has an id")


def test_a_finished_handoff_reads_its_report_through_exact_node_selectors():
    fixture = HandoffFixture()

    result = fixture.read(include_excerpts=True)

    descriptor = result["descriptor"]
    _same(set(descriptor), {
        "version", "workflow_id", "run_id", "workflow_name", "status", "completed_at", "result_sha256", "available",
    }, "the descriptor keys")
    _same(descriptor["workflow_id"], WID, "the workflow id")
    _same(descriptor["run_id"], RUN, "the run id")
    _same(descriptor["workflow_name"], "Contract review", "the workflow name")
    _same(descriptor["status"], "completed", "the status")
    _same(descriptor["completed_at"], COMPLETED_AT, "the completion time")
    _same(descriptor["available"], True, "availability")
    _same(descriptor["result_sha256"], fixture.digest(), "the digest")
    _same(reader.workflow_result_context(descriptor), {
        "workflow_id": WID, "run_id": RUN, "result_sha256": fixture.digest(),
    }, "the browser context")
    _same({key: value for key, value in result.items() if key not in {"descriptor", "excerpts"}}, {
        "partial": False, "output_count": 1, "saved_inputs": [], "truncated": False,
        "omitted_outputs": 0, "skipped_reports": 0, "analysis_only": False,
    }, "the result summary")
    _same(result["excerpts"], [{
        "label": "Board summary", "kind": "text", "final": True, "text": REPORT_TEXT, "truncated": False, "note": None,
    }], "the excerpts")
    _same(fixture.store.loads, [fixture.reference["sha256"], fixture.text_reference["sha256"]], "the loads")
    _same(fixture.store.pages, [], "the page reads")
    _same(fixture.store.selectors, [
        ("load", fixture.reference["sha256"], fixture.selectors),
        ("load", fixture.text_reference["sha256"], fixture.selectors),
    ], "the selectors")
    _same(fixture.selectors["node_id"], "report-node", "the report node")
    _same(fixture.selectors["iteration_path"], [], "the report's iteration path")


def test_the_descriptor_alone_loads_only_the_manifest():
    fixture = HandoffFixture()

    result = fixture.read()

    _same(result["excerpts"], [], "the excerpts")
    _same(result["descriptor"]["result_sha256"], fixture.digest(), "the digest")
    _same(fixture.store.loads, [fixture.reference["sha256"]], "the loads")


def test_a_stored_context_authorizes_against_the_digest():
    fixture = HandoffFixture()
    digest = fixture.digest()

    matched = fixture.read(expected_sha256=digest)
    context = reader.workflow_result_context(matched["descriptor"])
    descriptor = reader.authorize_workflow_result_context(
        USER, context, containers=fixture.containers, load_result=fixture.store.load, read_page=fixture.store.read_page,
    )
    _same(descriptor, matched["descriptor"], "the authorized descriptor")

    fixture.reset()
    _refused(fixture, "workflow_result_changed", expected_sha256="b" * 64)
    _unread(fixture, "a changed digest")
    _refused(fixture, "workflow_result_invalid_context", expected_sha256="B" * 64)
    _unread(fixture, "a malformed digest")


@pytest.mark.parametrize("status, code", [
    ("failed", "workflow_result_not_finished"),
    ("invalid", "workflow_result_not_finished"),
    ("incomplete", "workflow_result_not_finished"),
    ("cancelled", "workflow_result_not_finished"),
    ("skipped", "workflow_result_not_finished"),
    ("running", "workflow_result_in_progress"),
    ("queued", "workflow_result_in_progress"),
    ("pending", "workflow_result_in_progress"),
])
def test_an_unfinished_handoff_is_closed_before_any_read(status, code):
    fixture = HandoffFixture(status=status)

    _refused(fixture, code, include_excerpts=True)

    _unread(fixture, status)


def test_accepted_partial_findings_read_only_on_a_partial_run():
    partial = HandoffFixture(status="completed_partial", partial=True)
    result = partial.read(include_excerpts=True)
    _same(result["partial"], True, "the partial flag")
    _same(result["descriptor"]["status"], "completed_partial", "the status")
    _same(result["descriptor"]["result_sha256"], partial.digest("completed_partial"), "the partial digest")
    _require(result["descriptor"]["result_sha256"] != partial.digest(), "The digest ignores the run status.")

    completed = HandoffFixture(status="completed", partial=True)
    _refused(completed, "workflow_result_invalid", include_excerpts=True)


@pytest.mark.parametrize("variant", ["definition_edit", "enable_toggle", "alert_edit", "run_as"])
def test_an_edited_or_re_enabled_definition_fails_closed(variant):
    fixture = HandoffFixture()
    if variant == "definition_edit":
        fixture.workflow["tasks"][1]["instructions"] = "Write a different report."
    elif variant == "enable_toggle":
        fixture.workflow["is_enabled"] = True
    elif variant == "alert_edit":
        fixture.workflow["alert_mode"] = "always"
    else:
        fixture.workflow["m365_run_as_user_id"] = "user-other-2"

    _refused(fixture, "workflow_result_invalid", include_excerpts=True)

    _unread(fixture, variant)


def test_runtime_fields_written_after_the_run_keep_it_readable():
    fixture = HandoffFixture()
    fixture.workflow.update({
        "one_time_status": {"state": "completed", "run_id": RUN, "completed_at": COMPLETED_AT},
        "last_run_at": COMPLETED_AT, "last_run_status": "completed", "modified_at": COMPLETED_AT,
        "active_run_id": None,
    })

    result = fixture.read(include_excerpts=True)

    _same(result["excerpts"][0]["text"], REPORT_TEXT, "the report text")
    _same(result["descriptor"]["result_sha256"], fixture.digest(), "the digest")


@pytest.mark.parametrize("variant", ["execution_id", "attempt_zero", "attempt_text", "workflow_id", "run_id"])
def test_a_tampered_producer_is_refused_before_any_read(variant):
    fixture = HandoffFixture()
    producer = fixture.receipt["producer"]
    if variant == "execution_id":
        producer["execution_id"] = "e" * 64
    elif variant == "attempt_zero":
        producer["attempt"] = 0
    elif variant == "attempt_text":
        producer["attempt"] = "1"
    elif variant == "workflow_id":
        producer["workflow_id"] = "wf-other-1"
    else:
        producer["run_id"] = "run-other-1"

    _refused(fixture, "workflow_result_invalid", include_excerpts=True)

    _unread(fixture, variant)


def test_a_receipt_that_disagrees_with_its_manifest_is_refused():
    fixture = HandoffFixture()
    fixture.receipt["producer"]["attempt"] = 2
    _refused(fixture, "workflow_result_invalid", include_excerpts=True)
    _same(fixture.store.loads, [fixture.reference["sha256"]], "the loads for a later attempt")

    fixture = HandoffFixture()
    fixture.receipt["output_ref"] = {"sha256": "c" * 64, "size_bytes": 10}
    _refused(fixture, "workflow_result_invalid", include_excerpts=True)
    _same(fixture.store.loads, [fixture.reference["sha256"]], "the loads for another output")

    fixture = HandoffFixture()
    fixture.receipt["result_ref"] = dict(fixture.text_reference)
    _refused(fixture, "workflow_result_invalid", include_excerpts=True)


def test_store_failures_map_to_closed_reasons():
    fixture = HandoffFixture()
    del fixture.store.contents[fixture.reference["sha256"]]
    _refused(fixture, "workflow_result_not_found")

    fixture = HandoffFixture()
    del fixture.store.contents[fixture.text_reference["sha256"]]
    _refused(fixture, "workflow_result_not_found", include_excerpts=True)

    fixture = HandoffFixture()
    fixture.store.load_error = AzureError("storage is down")
    error = _refused(fixture, "workflow_result_storage_unavailable")
    _same(error.status, 503, "the storage status")
    _require("storage is down" not in error.message, "The closed message carries exception text.")


def test_a_json_authoritative_report_still_reads_its_text():
    reply = "Two contracts need an owner; the table follows."
    fixture = HandoffFixture(result={"reply": reply, "authoritative_result": {"kind": "json", "value": {"owners": 2}}})
    _same(fixture.manifest["authoritative_output"], "json", "the authoritative output")

    result = fixture.read(include_excerpts=True)

    _same(result["excerpts"][0]["kind"], "text", "the excerpt kind")
    _same(result["excerpts"][0]["text"], reply, "the excerpt text")
    _same(result["descriptor"]["result_sha256"], fixture.digest(), "the digest names the text output")


def test_a_large_report_is_paged_once_by_its_selectors():
    report = "Finding. " * 34000
    fixture = HandoffFixture(result={"reply": report})
    _require(fixture.text_reference["size_bytes"] > reader.FULL_SECTION_READ_BYTES, "The report isn't large.")

    result = fixture.read(include_excerpts=True)

    excerpt = result["excerpts"][0]
    limit = min(MAX_PAGE_BYTES, DEFAULT_BUDGET * 3 + 4096)
    _same(fixture.store.pages, [(fixture.text_reference["sha256"], 0, limit)], "the page reads")
    _same(fixture.store.loads, [fixture.reference["sha256"]], "the loads")
    _same(fixture.store.selectors[-1], ("page", fixture.text_reference["sha256"], fixture.selectors), "page selectors")
    _require(excerpt["truncated"] is True and result["truncated"] is True, "A large report isn't marked truncated.")
    _require(excerpt["note"].startswith("[Excerpt truncated"), f"The note is {excerpt['note']!r}.")
    _require(len(excerpt["text"].encode("utf-8")) <= DEFAULT_BUDGET, "The excerpt exceeds its budget.")
    _require(report.startswith(excerpt["text"]), "The excerpt isn't the report's start.")


def test_a_small_budget_cuts_the_report():
    report = "Finding about indemnity. " * 220
    fixture = HandoffFixture(result={"reply": report})

    result = fixture.read(include_excerpts=True, excerpt_budget_bytes=1024)

    excerpt = result["excerpts"][0]
    _same(len(excerpt["text"].encode("utf-8")), 1024, "the excerpt size")
    _require(excerpt["truncated"] is True, "The excerpt isn't marked truncated.")
    _same(excerpt["note"], "[Excerpt truncated: the first 1 KB of 6 KB.]", "the note")
    _same(fixture.store.pages, [], "the page reads")


@pytest.mark.parametrize("title, label", [
    ("   ", "Report"),
    ("Board\nsummary", "Board summary"),
    ("Board\x00\tsummary  ", "Board summary"),
    ("R" * 200, "R" * 120),
])
def test_the_excerpt_label_is_the_report_task_name(title, label):
    fixture = HandoffFixture(title=title)

    result = fixture.read(include_excerpts=True)

    _same(result["excerpts"][0]["label"], label, "the label")


def test_the_model_facing_result_carries_no_store_references_or_ids():
    fixture = HandoffFixture()

    result = fixture.read(include_excerpts=True)

    body = json.dumps({key: value for key, value in result.items() if key != "descriptor"})
    for secret in (
        fixture.reference["sha256"], fixture.text_reference["sha256"], WID, RUN, fixture.task_id,
        fixture.selectors["execution_id"], HANDOFF_ID, CONVERSATION, USER,
    ):
        _require(secret not in body, f"The result carries {secret!r}.")
    descriptor = json.dumps(result["descriptor"])
    for secret in (fixture.reference["sha256"], fixture.text_reference["sha256"], fixture.task_id, HANDOFF_ID):
        _require(secret not in descriptor, f"The descriptor carries {secret!r}.")


def test_the_default_loaders_are_the_node_level_store(monkeypatch):
    fixture = HandoffFixture(result={"reply": "Finding. " * 34000})

    def task_level(*args, **kwargs):
        raise AssertionError("A hand-off read used the task-level result store.")

    monkeypatch.setattr(reader, "load_workflow_node_result", fixture.store.load)
    monkeypatch.setattr(reader, "read_workflow_node_result_page", fixture.store.read_page)
    monkeypatch.setattr(reader, "load_workflow_task_result", task_level)
    monkeypatch.setattr(reader, "read_workflow_task_result_page", task_level)

    result = reader.read_workflow_result(USER, WID, RUN, containers=fixture.containers, include_excerpts=True)

    _require(result["excerpts"][0]["truncated"] is True, "The large report wasn't paged.")
    _same([entry[0] for entry in fixture.store.selectors], ["load", "page"], "the default reads")
    _require(all(entry[2] == fixture.selectors for entry in fixture.store.selectors), "A default read lost its selectors.")


def _edit(target, path, value):
    *parents, last = path
    for key in parents:
        target = target[key]
    if value is _DELETE:
        target.pop(last)
    else:
        target[last] = value


_DELETE = object()
_GATES = {
    "trigger_manual": ("run", ("trigger_source",), "manual"),
    "trigger_missing": ("run", ("trigger_source",), _DELETE),
    "origin_missing": ("workflow", ("origin",), _DELETE),
    "origin_text": ("workflow", ("origin",), "orchestration"),
    "one_time_missing": ("workflow", ("origin", "one_time"), _DELETE),
    "one_time_false": ("workflow", ("origin", "one_time"), False),
    "one_time_text": ("workflow", ("origin", "one_time"), "true"),
    "one_time_number": ("workflow", ("origin", "one_time"), 1),
    "invocation_missing": ("run", ("chat_invocation",), _DELETE),
    "invocation_text": ("run", ("chat_invocation",), "chat"),
    "handoff_id_missing": ("run", ("chat_invocation", "handoff_id"), _DELETE),
    "handoff_id_empty": ("run", ("chat_invocation", "handoff_id"), ""),
    "handoff_id_number": ("run", ("chat_invocation", "handoff_id"), 7),
    "handoff_id_other": ("run", ("chat_invocation", "handoff_id"), "handoff-other"),
    "proposal_id_other": ("workflow", ("origin", "proposal_id"), "handoff-other"),
    "outputs_empty": ("run", ("workflow_outputs",), []),
    "outputs_mapping": ("run", ("workflow_outputs",), {"report": "value"}),
    "outputs_text": ("run", ("workflow_outputs",), ["x"]),
    "input_findings": ("run", ("workflow_outputs", 0, "input_name"), "findings"),
    "input_missing": ("run", ("workflow_outputs", 0, "input_name"), _DELETE),
    "output_records": ("run", ("workflow_outputs", 0, "output_name"), "records"),
    "body_node": ("run", ("workflow_outputs", 0, "producer", "node_id"), "body-node"),
    "producer_text": ("run", ("workflow_outputs", 0, "producer"), "report-node"),
    "task_id_number": ("run", ("workflow_outputs", 0, "producer", "task_id"), 1),
    "task_id_missing": ("run", ("workflow_outputs", 0, "producer", "task_id"), _DELETE),
    "output_ref_missing": ("run", ("workflow_outputs", 0, "output_ref"), _DELETE),
    "output_ref_text": ("run", ("workflow_outputs", 0, "output_ref"), "x"),
    "result_ref_missing": ("run", ("workflow_outputs", 0, "result_ref"), _DELETE),
    "result_ref_text": ("run", ("workflow_outputs", 0, "result_ref"), "x"),
    "result_sha_upper": ("run", ("workflow_outputs", 0, "result_ref", "sha256"), "A" * 64),
    "result_sha_short": ("run", ("workflow_outputs", 0, "result_ref", "sha256"), "a" * 10),
    "result_sha_number": ("run", ("workflow_outputs", 0, "result_ref", "sha256"), 7),
}


@pytest.mark.parametrize("variant", sorted(_GATES))
def test_every_other_structured_shape_stays_closed_with_no_read(variant):
    fixture = HandoffFixture()
    document, path, value = _GATES[variant]
    _edit(fixture.workflow if document == "workflow" else fixture.run, path, value)

    error = _refused(fixture, "workflow_result_unsupported", include_excerpts=True)

    _same(error.status, 409, "the status")
    _unread(fixture, variant)


def test_two_outputs_or_another_handoff_stay_closed():
    fixture = HandoffFixture()
    fixture.run["workflow_outputs"].append(deepcopy(fixture.receipt))
    _refused(fixture, "workflow_result_unsupported", include_excerpts=True)
    _unread(fixture, "two outputs")

    # Both ids agree, but the workflow isn't the one that hand-off creates.
    fixture = HandoffFixture()
    fixture.workflow["origin"]["proposal_id"] = "handoff-other"
    fixture.run["chat_invocation"]["handoff_id"] = "handoff-other"
    _refused(fixture, "workflow_result_unsupported", include_excerpts=True)
    _unread(fixture, "another hand-off")

    fixture = HandoffFixture()
    fixture.workflow["id"] = fixture.run["workflow_id"] = "wf-other-1"
    _refused(fixture, "workflow_result_unsupported", workflow_id="wf-other-1", include_excerpts=True)
    _unread(fixture, "another workflow id")


def test_a_chat_run_of_a_proposed_structured_workflow_stays_closed():
    # Phase 5 runs an accepted proposal with the same trigger, but it isn't one-time or a hand-off.
    fixture = HandoffFixture()
    fixture.workflow["origin"].pop("one_time")
    fixture.run["chat_invocation"].pop("handoff_id")

    _refused(fixture, "workflow_result_unsupported", include_excerpts=True)

    _unread(fixture, "a proposed workflow")


_READS = (("excerpts", {"include_excerpts": True}), ("descriptor", {}))
_LINEAGE_INVALID = {"code": "workflow_result_invalid", "stage": "authorize", "error_type": "AnalysisResultUnavailable"}


def test_a_malformed_consumed_input_receipt_is_refused_before_the_report_is_read(monkeypatch):
    # Saved under its own valid hash, so the identity, output and completion checks all pass.
    fixture = HandoffFixture()
    manifest = deepcopy(fixture.manifest)
    manifest["consumed_inputs"] = [{"malformed_receipt": True}]
    reference = _repoint(fixture, manifest)
    fixture.reset()
    logged = _closed_stages(monkeypatch)

    for label, options in _READS:
        _refused(fixture, "workflow_result_invalid", **options)
        _same(fixture.store.loads, [reference["sha256"]], f"{label}: the loads")
        _require(fixture.text_reference["sha256"] not in fixture.store.loads, f"{label}: the report's text was loaded.")
        _same(fixture.store.pages, [], f"{label}: the page reads")
        _same(logged, [_LINEAGE_INVALID], f"{label}: the closed stage")
        fixture.reset()
        logged.clear()

    context = {"workflow_id": WID, "run_id": RUN, "result_sha256": _digest_for(fixture, reference)}
    error = closed(lambda: reader.authorize_workflow_result_context(
        USER, context, containers=fixture.containers, load_result=fixture.store.load, read_page=fixture.store.read_page,
    ))
    _same(error.code, "workflow_result_invalid", "the stored context's closed reason")
    _same(fixture.store.loads, [reference["sha256"]], "the stored context's loads")
    _same(fixture.store.pages, [], "the stored context's page reads")
    _same(logged, [_LINEAGE_INVALID], "the stored context's closed stage")

    # Without the walk the same manifest reads as a normal report, so the refusal is the walk's.
    monkeypatch.setattr(reader, "authorize_workflow_node_result_read", lambda *args, **kwargs: None)
    fixture.reset()
    unwalked = fixture.read(include_excerpts=True)
    _same(unwalked["descriptor"]["available"], True, "availability without the walk")
    _same(unwalked["excerpts"][0]["text"], REPORT_TEXT, "the report text without the walk")


def test_a_report_with_real_lineage_reads_after_walking_its_parent(monkeypatch):
    fixture = LineageFixture()
    report, collect, text = (
        fixture.reference["sha256"], fixture.collect_reference["sha256"], fixture.text_reference["sha256"],
    )
    _same(fixture.manifest["consumed_inputs"], [{
        "producer": fixture.collect_identity, "output_name": "records", "result_ref": fixture.collect_reference,
        "output_ref": fixture.collect_manifest["outputs"]["records"]["result_ref"], "input_name": "findings",
    }], "the report's consumed-input receipt")
    _same(fixture.collect_identity["node_id"], "collect", "the parent node")

    result = fixture.read(include_excerpts=True)

    _same(result["descriptor"]["available"], True, "availability")
    _same(result["descriptor"]["result_sha256"], fixture.digest(), "the digest")
    _same(result["excerpts"], [{
        "label": "Board summary", "kind": "text", "final": True, "text": REPORT_TEXT, "truncated": False, "note": None,
    }], "the excerpts")
    _same(fixture.store.loads, [report, collect, text], "the loads: the manifest, its lineage, then the text section")
    _same(fixture.store.pages, [], "the page reads")
    _same(fixture.store.selectors, [
        ("load", report, fixture.selectors),
        ("load", collect, result_selectors(fixture.collect_identity)),
        ("load", text, fixture.selectors),
    ], "the selectors")

    # Without the walk the result is identical and only the parent's load disappears, so this
    # control passes by walking real lineage, not because there was nothing to walk.
    calls = []

    def skip_walk(workflow, run_id, identity, reference, **options):
        calls.append({
            "run_id": run_id, "identity": identity, "reference": reference,
            "reader_user_id": options.get("reader_user_id"), "manifest": options.get("manifest"),
        })

    monkeypatch.setattr(reader, "authorize_workflow_node_result_read", skip_walk)
    fixture.reset()
    _same(fixture.read(include_excerpts=True), result, "the result without the walk")
    _same(fixture.store.loads, [report, text], "the loads without the walk")
    _same(calls, [{
        "run_id": RUN, "identity": fixture.manifest["identity"], "reference": fixture.reference,
        "reader_user_id": USER, "manifest": fixture.manifest,
    }], "the walk's arguments")


def test_a_descriptor_alone_walks_the_lineage_but_reads_no_section():
    fixture = LineageFixture()
    expected = [fixture.reference["sha256"], fixture.collect_reference["sha256"]]

    result = fixture.read()

    _same(result["excerpts"], [], "the excerpts")
    _same(result["descriptor"]["available"], True, "availability")
    _same(result["descriptor"]["result_sha256"], fixture.digest(), "the digest")
    _same(fixture.store.loads, expected, "the loads")
    _same(fixture.store.pages, [], "the page reads")

    fixture.reset()
    descriptor = reader.authorize_workflow_result_context(
        USER, reader.workflow_result_context(result["descriptor"]), containers=fixture.containers,
        load_result=fixture.store.load, read_page=fixture.store.read_page,
    )
    _same(descriptor, result["descriptor"], "the authorized descriptor")
    _same(fixture.store.loads, expected, "the stored context's loads")
    _same(fixture.store.pages, [], "the stored context's page reads")


def test_a_missing_parent_is_refused_with_the_general_paths_code(monkeypatch):
    fixture = LineageFixture()
    del fixture.store.contents[fixture.collect_reference["sha256"]]
    logged = _closed_stages(monkeypatch)
    missing = {"code": "workflow_result_not_found", "stage": "authorize", "error_type": "CosmosResourceNotFoundError"}
    walked = [fixture.reference["sha256"], fixture.collect_reference["sha256"]]

    for label, options in _READS:
        error = _refused(fixture, "workflow_result_not_found", **options)
        _same(error.status, 404, f"{label}: the status")
        _same(fixture.store.loads, walked, f"{label}: the loads")
        _same(fixture.store.pages, [], f"{label}: the page reads")
        _same(logged, [missing], f"{label}: the closed stage")
        fixture.reset()
        logged.clear()

    # The general path walks the same lineage for each task row. This report consumed a parent
    # whose row and stored result are both gone, so only the walk can reach the missing parent.
    general = RunFixture()
    _, parent = general.add_task("task-collect-1", analysis_result(), order=1)
    general.add_task("task-report-2", {"reply": REPORT_TEXT}, order=2, consumed=[
        general.receipt("task-collect-1", parent),
    ])
    general.items[:] = [item for item in general.items if item["task_id"] != "task-collect-1"]
    del general.store.contents[parent["sha256"]]
    general.reset_counters()

    error = closed(lambda: general.read(include_excerpts=True))

    _same(error.code, "workflow_result_not_found", "the general path's closed reason")
    _same(error.status, 404, "the general path's status")
    _same(general.store.loads[-1:], [parent["sha256"]], "the general path's last load, the missing parent")
    _same(logged, [missing], "the general path's closed stage")


def _wrong_receipt_output(receipt, parent, save):
    receipt["output_ref"] = {"sha256": "c" * 64, "size_bytes": 10}


def _wrong_parent_output(receipt, parent, save):
    # A parent saved under its own valid hash whose records output names another section.
    altered = deepcopy(parent)
    altered["outputs"]["records"]["result_ref"] = deepcopy(altered["outputs"]["text"]["result_ref"])
    receipt["result_ref"] = save(altered)


@pytest.mark.parametrize("tamper", [_wrong_receipt_output, _wrong_parent_output], ids=["receipt", "parent"])
def test_a_parent_whose_output_disagrees_with_the_receipt_is_refused(tamper, monkeypatch):
    fixture = LineageFixture(tamper=tamper)
    parent = fixture.manifest["consumed_inputs"][0]["result_ref"]["sha256"]
    logged = _closed_stages(monkeypatch)

    for label, options in _READS:
        _refused(fixture, "workflow_result_invalid", **options)
        _same(fixture.store.loads, [fixture.reference["sha256"], parent], f"{label}: the loads")
        _same(fixture.store.pages, [], f"{label}: the page reads")
        _same(logged, [_LINEAGE_INVALID], f"{label}: the closed stage")
        fixture.reset()
        logged.clear()


def test_a_parent_whose_bytes_do_not_match_its_hash_is_refused(monkeypatch):
    fixture = LineageFixture()
    load = _verifying(fixture.store)
    verified = fixture.read(include_excerpts=True, load_result=load)
    _same(verified["excerpts"][0]["text"], REPORT_TEXT, "the verified read")
    # Same length, different bytes: only the digest disagrees.
    altered = deepcopy(fixture.collect_manifest)
    altered["summary"] = altered["summary"].replace("two", "six")
    _require(altered != fixture.collect_manifest, "The parent wasn't altered.")
    _same(len(canonical(altered)), fixture.collect_reference["size_bytes"], "the altered parent's size")
    fixture.store.contents[fixture.collect_reference["sha256"]] = canonical(altered)
    fixture.reset()
    logged = _closed_stages(monkeypatch)
    walked = [fixture.reference["sha256"], fixture.collect_reference["sha256"]]

    for label, options in _READS:
        _refused(fixture, "workflow_result_invalid", load_result=load, **options)
        _same(fixture.store.loads, walked, f"{label}: the loads")
        _same(fixture.store.pages, [], f"{label}: the page reads")
        _same(logged, [{
            "code": "workflow_result_invalid", "stage": "authorize", "error_type": "WorkflowResultIntegrityError",
        }], f"{label}: the closed stage")
        fixture.reset()
        logged.clear()


@pytest.mark.parametrize("variant", ["definition_edit", "enable_toggle", "alert_edit", "run_as"])
def test_an_edited_or_re_enabled_definition_with_lineage_fails_closed(variant):
    fixture = LineageFixture()
    if variant == "definition_edit":
        fixture.workflow["tasks"][1]["instructions"] = "Write a different report."
    elif variant == "enable_toggle":
        fixture.workflow["is_enabled"] = True
    elif variant == "alert_edit":
        fixture.workflow["alert_mode"] = "always"
    else:
        fixture.workflow["m365_run_as_user_id"] = "user-other-2"

    for label, options in _READS:
        _refused(fixture, "workflow_result_invalid", **options)
        _unread(fixture, f"{variant}, {label}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
