# test_orchestration_external_results.py
"""
Bounded external Gather provenance, admission and current authorization.
Version: 0.261.125
Implemented in: 0.261.125

No external resource is fetched. Server catalogs and current access metadata are
external-I/O doubles; real contracts, private storage and readers are exercised.
"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from functions_orchestration_result_contracts import (
    EXTERNAL_LINEAGE_VERSION,
    EXTERNAL_SOURCE_VERSION,
    RESULT_MANIFEST_VERSION,
    ExternalSourceRef,
    ResultContractError,
)
from functions_orchestration_results import (
    NamedOutput,
    OrchestrationResultAccess,
    OrchestrationResults,
    ResultUnavailableError,
)
from test_support.orchestration_results import ResultFixture, complete
from test_support.versioning import assert_app_version_at_least


CAPABILITIES = {
    "web": "web_search", "url": "url_fetch", "deep_research": "deep_research",
    "agent": "agent_invoke", "action": "action_invoke", "fact_memory": "fact_memory",
}
PREPARED = {
    "findings": ["Retained first finding.", "Retained final finding."],
    "display_url": "https://public.example/retained-provenance",
}


def test_external_lineage_foundation_version():
    assert_app_version_at_least("0.261.125")


class ExternalFixture(ResultFixture):
    def __init__(self, source_type="web"):
        super().__init__(blob=True)
        self.producer = replace(
            self.producer, step_id="gather", capability_id="agent_invoke", contract_version="gather-v1",
        )
        self.add_producer(self.producer)
        reference = ExternalSourceRef(
            source_type, CAPABILITIES[source_type], "server-resource-1", "personal:owner",
            content_sha256="1" * 64, source_revision="revision-1",
        )
        self.catalog_wire = {"admitted_source": reference.to_dict()}
        self.current = {reference.identity(): reference}
        self.enabled = {reference.capability_id}
        self.audiences = {reference.audience}
        self.calls = []
        self.service = self.reopen()

    def authorize_external(self, reference, *, producer, user_id, conversation_id):
        self.calls.append((reference, producer, user_id, conversation_id))
        if (
            user_id != "owner" or conversation_id != "conversation-1"
            or reference.capability_id not in self.enabled or reference.audience not in self.audiences
            or reference.identity() not in self.current
        ):
            raise PermissionError("The current capability, resource or audience is unavailable.")
        return self.current[reference.identity()]

    def reopen(self, *, catalog=True, authorizer=True):
        self.catalog_wire = json.loads(json.dumps(self.catalog_wire))
        access = OrchestrationResultAccess(
            user_id="owner", conversation_id="conversation-1",
            read_conversation=lambda conversation_id: deepcopy(self.conversation),
            read_run=lambda run_id: deepcopy(self.runs.get(run_id)),
            source_resolver=self.resolve, source_metadata_reader=self.metadata,
            external_source_catalog={
                alias: ExternalSourceRef.from_dict(value) for alias, value in self.catalog_wire.items()
            } if catalog else {},
            external_source_authorizer=self.authorize_external if authorizer else None,
        )
        return OrchestrationResults(self.restart().store, access)

    def retain(self, **changes):
        options = {
            "producer": self.producer, "role": "gather", "status": "complete",
            "outputs": [NamedOutput("knowledge", "structured-v1", deepcopy(PREPARED), complete(1))],
            "sources": [], "origin": "grounded", "guard_token": "owning-gather-token",
            "external_sources": ("admitted_source",),
        }
        return self.service.persist_task_result(**{**options, **changes})


@pytest.mark.parametrize("source_type", list(CAPABILITIES))
def test_each_external_type_is_retained_and_reauthorized_after_restart(source_type):
    fixture = ExternalFixture(source_type)
    task = fixture.retain(input_fingerprint="a" * 64)
    restarted = fixture.reopen(catalog=False)
    recovered = restarted.recover_task_result(producer=fixture.producer, input_fingerprint="a" * 64)
    reader = restarted.open_result(recovered.output("knowledge"))
    value = reader.read_value()
    metadata = reader.metadata()
    assert recovered == task and value == PREPARED
    assert metadata["origin"] == "grounded" and metadata["source_count"] == 0
    assert metadata["external_source_count"] == 1
    bindings = metadata["external_sources"]
    assert bindings == [{"alias": "admitted_source", "reference": fixture.catalog_wire["admitted_source"]}]
    assert bindings[0]["reference"]["version"] == EXTERNAL_SOURCE_VERSION
    assert all(call[1:] == (fixture.producer, "owner", "conversation-1") for call in fixture.calls)
    assert fixture.source_reads == []
    manifest = restarted.store.load_committed_orchestration_result(
        "owner", "conversation-1", "run-1", "gather", task.output("knowledge").manifest_sha256,
    )
    assert manifest["version"] == RESULT_MANIFEST_VERSION
    assert manifest["lineage"]["version"] == EXTERNAL_LINEAGE_VERSION
    assert manifest["lineage"]["external_sources"] == bindings
    encoded = json.dumps(manifest)
    assert "https://" not in encoded
    assert "authorize_external" not in encoded and "owning-gather-token" not in encoded


@pytest.mark.parametrize("source_type", list(CAPABILITIES))
@pytest.mark.parametrize("change", ["capability", "resource", "audience", "authorizer"])
def test_current_external_access_is_required_even_for_public_or_snapshot_sources(source_type, change):
    fixture = ExternalFixture(source_type)
    task = fixture.retain(source_policy="snapshot", input_fingerprint="a" * 64)
    if change == "capability":
        fixture.enabled.clear()
    elif change == "resource":
        fixture.current.clear()
    elif change == "audience":
        fixture.audiences.clear()
    restarted = fixture.reopen(authorizer=change != "authorizer")
    with pytest.raises(PermissionError):
        restarted.open_result(task.output("knowledge"))
    with pytest.raises(PermissionError):
        restarted.recover_task_result(producer=fixture.producer, input_fingerprint="a" * 64)


@pytest.mark.parametrize("field,value", [
    ("source_type", "action"), ("capability_id", "different-capability"),
    ("reference_id", "different-resource"), ("audience", "group:foreign"),
])
def test_current_authorizer_cannot_change_external_identity_or_audience(field, value):
    fixture = ExternalFixture()
    task = fixture.retain(source_policy="snapshot")
    identity, reference = next(iter(fixture.current.items()))
    fixture.current[identity] = replace(reference, **{field: value})
    with pytest.raises(ResultUnavailableError):
        fixture.reopen().open_result(task.output("knowledge"))


@pytest.mark.parametrize("field,value", [("source_revision", "changed"), ("content_sha256", "2" * 64)])
def test_current_policy_rejects_external_changes_but_snapshot_reads_original_data(field, value):
    fixture = ExternalFixture()
    current = fixture.retain()
    historical = fixture.retain(source_policy="snapshot")
    identity, reference = next(iter(fixture.current.items()))
    fixture.current[identity] = replace(reference, **{field: value})
    with pytest.raises(ResultUnavailableError):
        fixture.reopen().open_result(current.output("knowledge"))
    reader = fixture.reopen().open_result(historical.output("knowledge"))
    value = reader.read_value()
    metadata = reader.metadata()
    assert value == PREPARED and metadata["source_snapshot_changed"] is True
    assert metadata["external_sources"][0]["reference"] == reference.to_dict()
    with pytest.raises(ResultUnavailableError):
        fixture.reopen().open_result(historical.output("knowledge"), require_current_sources=True)


def test_stored_admissions_can_be_restored_without_a_python_catalog_cache():
    fixture = ExternalFixture()
    task = fixture.retain()
    restarted = fixture.reopen(catalog=False)
    reader = restarted.open_result(task.output("knowledge"))
    restored = reader.metadata()["external_sources"]
    with pytest.raises(ResultContractError):
        restarted.access.admit_external_sources(("admitted_source",))
    fixture.catalog_wire = {
        binding["alias"]: binding["reference"] for binding in json.loads(json.dumps(restored))
    }
    fixture.service = fixture.reopen()
    again = fixture.retain()
    assert again == task


def test_transitive_external_lineage_is_authorized_using_the_original_producer():
    fixture = ExternalFixture("fact_memory")
    task = fixture.retain(source_policy="snapshot")
    child_producer = fixture.consumer()
    child = fixture.service.persist_task_result(
        producer=child_producer, role="reason", status="complete",
        outputs=[NamedOutput("summary", "text-v1", "Prepared from retained facts.", complete(1))],
        sources=[], origin="grounded", guard_token="child-token",
        upstream=(task.output("knowledge"),), source_policy="snapshot",
    )
    child_reader = fixture.reopen(catalog=False).open_result(child.output("summary"))
    metadata = child_reader.metadata()
    assert metadata["external_source_count"] == 1
    assert all(call[1] == fixture.producer for call in fixture.calls)
    fixture.audiences.clear()
    with pytest.raises(PermissionError):
        child_reader.read_text()


@pytest.mark.parametrize("aliases", [
    ("not_admitted",), ("admitted_source", "admitted_source"),
    "admitted_source", ({"url": "https://untrusted.example"},),
])
def test_model_values_cannot_become_admitted_external_sources(aliases):
    fixture = ExternalFixture()
    with pytest.raises(ResultContractError):
        fixture.retain(external_sources=aliases)
    assert fixture.container.items == {}


def test_duplicate_external_identity_and_catalog_limits_are_explicit():
    fixture = ExternalFixture()
    fixture.catalog_wire["duplicate"] = fixture.catalog_wire["admitted_source"]
    fixture.service = fixture.reopen()
    with pytest.raises(ResultContractError):
        fixture.retain(external_sources=("admitted_source", "duplicate"))
    fixture.catalog_wire = {f"alias_{index}": fixture.catalog_wire["admitted_source"] for index in range(65)}
    with pytest.raises(ResultContractError):
        fixture.reopen()


@pytest.mark.parametrize("extra", [
    {"url": "https://untrusted.example"}, {"credentials": "not-allowed"},
    {"callback": "not-allowed"}, {"prompt": "raw-memory-prompt"}, {"storage": "foreign"},
])
def test_external_wire_never_accepts_fetch_instructions_or_runtime_context(extra):
    reference = ExternalSourceRef("web", "web_search", "server-ref", "personal:owner", source_revision="v1")
    with pytest.raises(ResultContractError):
        ExternalSourceRef.from_dict({**reference.to_dict(), **extra})


@pytest.mark.parametrize("changes", [
    {"content_sha256": None, "source_revision": None},
    {"source_type": "untyped"},
    {"reference_id": "https://public.example/resource"},
    {"audience": "personal:owner\nforeign"},
    {"content_sha256": "not-a-digest"},
    {"source_revision": "v" * 257},
    {"source_revision": "raw\nprompt"},
    {"version": "unknown"},
])
def test_external_descriptor_is_strict_and_bounded(changes):
    value = ExternalSourceRef("web", "web_search", "server-ref", "personal:owner", source_revision="v1").to_dict()
    with pytest.raises(ResultContractError):
        ExternalSourceRef.from_dict({**value, **changes})


@pytest.mark.parametrize("returned", [None, True, {}, "authorized"])
def test_external_authorizer_never_uses_success_shaped_fallbacks(returned):
    fixture = ExternalFixture()
    fixture.service.access.external_source_authorizer = lambda *args, **kwargs: returned
    with pytest.raises(ResultUnavailableError):
        fixture.retain()
    assert fixture.container.items == {}


def test_external_lineage_cannot_be_mislabeled_as_source_free():
    fixture = ExternalFixture()
    with pytest.raises(ResultContractError):
        fixture.retain(origin="generated")
    assert fixture.container.items == {}
