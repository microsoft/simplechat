# test_cosmos_document_boundaries.py
"""Functional contracts for the SDK document boundary and reviewed owner inventory.

Version: 0.261.324
Implemented in: 0.261.324

No cloud client, configuration bootstrap, or network service is required.
"""

import ast
import importlib
import importlib.util
from importlib.metadata import version
import json
import subprocess
import sys
from collections import UserDict
from copy import deepcopy
from pathlib import Path
from types import MappingProxyType

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict

from cosmos_document_utils import normalize_cosmos_document
from functions_orchestration_result_contracts import ResultContractError, validate_json
from test_support.m365 import CosmosContainer
from test_support.orchestration_revisions import AtomicMemoryContainer


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cosmos_boundary_checker", ROOT / "scripts" / "check_cosmos_response_boundaries.py",
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


@pytest.mark.parametrize("wrapper", [dict, UserDict, MappingProxyType, lambda value: CosmosDict(value, response_headers={})])
def test_document_normalizer_preserves_fields_etag_and_nested_identity(wrapper):
    nested = {"rows": [{"value": "untouched"}]}
    source = wrapper({"id": "record", "_etag": '"etag-1"', "_rid": "retained", "nested": nested})
    result = normalize_cosmos_document(source)
    assert type(result) is dict
    assert result == source and result is not source
    assert result["nested"] is nested
    assert result["_etag"] == '"etag-1"' and result["_rid"] == "retained"
    result["new"] = True
    assert "new" not in source


@pytest.mark.parametrize("value", [None, [], [("id", "record")], "record", 0, object()])
def test_document_normalizer_rejects_non_documents(value):
    with pytest.raises(TypeError):
        normalize_cosmos_document(value)


def test_real_sdk_copy_is_not_normalization_and_domain_validator_stays_strict():
    source = CosmosDict({"id": "record", "_etag": "etag"}, response_headers={"x-ms-request-charge": "1"})
    copied = deepcopy(source)
    assert type(copied) is CosmosDict
    with pytest.raises(ResultContractError):
        validate_json(copied)
    normalized = normalize_cosmos_document(source)
    validate_json(normalized)
    nested_mapping = UserDict({"value": "not-domain-json"})
    value = normalize_cosmos_document({"nested": nested_mapping})
    assert value["nested"] is nested_mapping
    with pytest.raises(ResultContractError):
        validate_json(value)


def test_installed_sdk_matches_the_application_dependency_pin():
    requirements = (ROOT / "application" / "single_app" / "requirements.txt").read_text(encoding="utf-8")
    pins = [line.split("==", 1)[1] for line in requirements.splitlines() if line.startswith("azure-cosmos==")]
    installed = version("azure-cosmos")
    assert len(pins) == 1 and installed == pins[0]


@pytest.mark.parametrize("optimized", [False, True])
def test_utility_cold_import_has_no_bootstrap_or_sdk_dependency(optimized):
    probe = """
import importlib.abc
import socket
import sys
def blocked(*args, **kwargs):
    raise RuntimeError('network forbidden')
socket.socket.connect = blocked
class RejectBootstrap(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'config', 'azure', 'functions_settings', 'functions_appinsights'}:
            raise RuntimeError('unexpected dependency: ' + fullname)
sys.meta_path.insert(0, RejectBootstrap())
from cosmos_document_utils import normalize_cosmos_document
result = normalize_cosmos_document({'id': 'offline', '_etag': 'preserved'})
if type(result) is not dict or result['_etag'] != 'preserved':
    raise RuntimeError('invalid normalized document')
try:
    normalize_cosmos_document([('id', 'offline')])
except TypeError:
    pass
else:
    raise RuntimeError('non-mapping accepted')
"""
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", probe],
        cwd=ROOT / "application" / "single_app", capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("sdk_responses", [False, True], ids=["explicit-plain", "sdk-default"])
@pytest.mark.parametrize("factory", [CosmosContainer, AtomicMemoryContainer])
def test_shared_double_point_shapes_query_rows_etags_and_atomicity(factory, sdk_responses):
    container = factory("group_id", sdk_responses=sdk_responses)
    created = container.create_item(body={"id": "record", "group_id": "owner", "value": {"n": 1}})
    read = container.read_item(item="record", partition_key="owner")
    updated = container.replace_item(
        item="record", body={**read, "value": {"n": 2}},
        etag=read["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    upserted = container.upsert_item(body={**updated, "value": {"n": 3}})
    expected = CosmosDict if sdk_responses else dict
    assert all(type(value) is expected for value in (created, read, updated, upserted))
    assert created["_etag"] == read["_etag"] != updated["_etag"] != upserted["_etag"]
    rows = list(container.query_items(query="SELECT * FROM c", partition_key="owner"))
    assert type(rows[0]) is dict and type(rows[0]["value"]) is dict
    with pytest.raises(exceptions.CosmosResourceNotFoundError):
        container.read_item(item="record", partition_key="someone-else")
    with pytest.raises(exceptions.CosmosHttpResponseError):
        container.replace_item(
            item="record", body=dict(read), etag=read["_etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    before = deepcopy(container.items)
    with pytest.raises((exceptions.CosmosHttpResponseError, exceptions.CosmosBatchOperationError)):
        container.execute_item_batch(
            batch_operations=[
                ("create", ({"id": "staged", "group_id": "owner"},)),
                ("replace", ("record", dict(upserted)), {"if_match_etag": "stale"}),
            ],
            partition_key="owner",
        )
    assert container.items == before


def test_shared_double_sdk_mode_is_the_default():
    for factory in (CosmosContainer, AtomicMemoryContainer):
        container = factory("group_id")
        response = container.create_item(body={"id": "record", "group_id": "owner"})
        assert type(response) is CosmosDict


@pytest.mark.parametrize("sdk_responses", [False, True])
@pytest.mark.parametrize("module_name,class_name,args", [
    ("test_workflow_result_store", "FakeCosmosContainer", ()),
    ("test_workflow_runtime_store", "FakeCosmosContainer", ()),
    ("test_support.offline_bootstrap", "OfflineContainer", ()),
    ("test_support.workflow_result_offline_app", "Container", ("run_id",)),
    ("test_support.workflow_chat_delivery_fakes", "FakeContainer", ("contract",)),
    ("test_support.orchestration_results", "ResultContainer", ()),
    ("test_support.orchestration_harness_execution", "HarnessMessageContainer", ()),
    ("test_orchestration_output_lifecycle", "OutputContainer", ()),
    ("test_orchestration_output_lifecycle", "MessageContainer", ()),
])
def test_migrated_workflow_and_bootstrap_doubles_keep_explicit_compatibility(
    module_name, class_name, args, sdk_responses,
):
    module = importlib.import_module(module_name)
    factory = getattr(module, class_name)
    container = factory(*args, sdk_responses=sdk_responses)
    created = container.create_item(body={
        "id": "record", "run_id": "owner", "conversation_id": "owner", "nested": {"value": "json"},
    })
    read = container.read_item(item="record", partition_key="owner")
    default_container = factory(*args)
    default = default_container.create_item(body={"id": "default", "run_id": "owner", "conversation_id": "owner"})
    expected = CosmosDict if sdk_responses else dict
    assert type(created) is type(read) is expected
    assert type(read["nested"]) is dict and type(default) is CosmosDict


def test_repository_boundary_inventory_has_no_unreviewed_or_stale_owners():
    inventory = json.loads(checker.INVENTORY.read_text(encoding="utf-8"))
    actual, doubles = checker.scan_boundaries(), checker.scan_doubles()
    errors = checker.validate_inventory(actual, doubles, inventory, domain_targets=checker.DOMAIN_DOUBLE_TARGETS)
    assert errors == [], "\n".join(errors)


def test_inventory_guard_rejects_new_changed_stale_and_unexplained_boundaries():
    boundary = {"sha256": "one", "points": [], "queries": []}
    review = {"boundary": boundary, "classification": "sdk-compatible", "contract": "mapping read", "tests": []}
    errors = checker.validate_inventory({"owner": boundary}, {}, {"owners": {"owner": review}})
    assert any("Missing runtime evidence" in error for error in errors)
    reviewed = {"owners": {"owner": {**review, "classification": "response-unused"}}}
    errors = checker.validate_inventory({"new": boundary, "owner": {**boundary, "sha256": "two"}}, {}, reviewed)
    assert any("Unreviewed" in error for error in errors)
    assert any("Changed" in error for error in errors)
    errors = checker.validate_inventory({}, {}, reviewed)
    assert any("Stale" in error for error in errors)
    refreshed = checker.refresh_inventory({"owner": {**boundary, "sha256": "two"}}, {}, reviewed)
    assert refreshed["owners"]["owner"]["classification"] == "review-required"


def test_inventory_distinguishes_unused_returned_helper_and_query_responses():
    visitor = checker.BoundaryVisitor()
    visitor.visit(ast.parse("""
def boundary(container):
    container.create_item(body={})
    reader = container.read_item
    rows = container.query_items(query='SELECT * FROM c')
    container.execute_item_batch(batch_operations=[])
    many = container.read_many(items=[])
    return container.read_item(item='id', partition_key='id')
"""))
    boundary = visitor.owners["boundary"]
    assert [entry["response"] for entry in boundary["points"]] == ["unused", "helper-reference", "returned"]
    assert boundary["queries"][0]["method"] == "query_items"
    assert [entry["method"] for entry in boundary["batches"]] == ["execute_item_batch", "read_many"]
    assert [entry["response"] for entry in boundary["batches"]] == ["unused", "consumed"]


def test_inventory_guard_rejects_stale_or_new_legacy_exemptions():
    boundary = {"sha256": "one", "points": [], "queries": []}
    legacy = {"boundary": boundary, "classification": "legacy-inline", "contract": "Existing inline Cosmos fake.", "tests": []}
    errors = checker.validate_inventory({}, {"new": boundary}, {"doubles": {"new": legacy}})
    assert any("cannot use legacy-inline" in error for error in errors)
    errors = checker.validate_inventory({}, {}, {"legacy_double_baseline": {"removed": "one"}})
    assert any("Stale legacy double exemption" in error for error in errors)
    review = {
        "boundary": boundary, "classification": "sdk-compatible", "contract": "Mapping field consumer.",
        "tests": [], "evidence_scope": "sdk-api-and-source-review",
    }
    errors = checker.validate_inventory({"new": boundary}, {}, {"owners": {"new": review}})
    assert any("owner-runtime SDK evidence" in error for error in errors)
    errors = checker.validate_inventory({}, {}, {"source_review_baseline": {"removed": "one"}})
    assert any("Stale source-only owner review" in error for error in errors)


def test_inventory_can_classify_a_similarly_named_non_cosmos_api_without_false_positive():
    boundary = {"sha256": "one", "points": [], "queries": []}
    review = {
        "boundary": boundary, "classification": "not-cosmos",
        "contract": "FileIndex.read_item returns a scalar filename; this injected API is not a Cosmos container.",
        "tests": [],
    }
    errors = checker.validate_inventory({"file-index": boundary}, {}, {"owners": {"file-index": review}})
    assert errors == []
    errors = checker.validate_inventory({}, {}, {"owners": {"file-index": review}})
    assert any("Stale" in error for error in errors)


def test_double_inventory_finds_nested_classes_namespace_and_point_fault_seams():
    doubles = checker.inspect_doubles("functional_tests/test_example.py", """
def test_first():
    class Container:
        def read_item(self):
            return {}
    mock = SimpleNamespace(read_item=lambda **kwargs: {})
    monkeypatch.setattr(mock, 'read_item', lambda **kwargs: None)
def test_second():
    class Container:
        def read_item(self):
            return {}
""")
    assert set(doubles) == {
        "functional_tests/test_example.py::test_first.Container",
        "functional_tests/test_example.py::test_second.Container",
        "functional_tests/test_example.py::test_first::point-seam-1",
        "functional_tests/test_example.py::test_first::point-seam-2",
    }


def test_inventory_includes_module_and_getattr_mediated_point_boundaries():
    visitor = checker.BoundaryVisitor()
    visitor.visit(ast.parse("""
settings = container.read_item(item='settings', partition_key='settings')
def owner(container):
    write = getattr(container, 'create_item', None)
    return getattr(container, 'read_item')(item='id', partition_key='id')
"""))
    assert visitor.owners["<module>"]["points"][0]["response"] == "consumed"
    points = visitor.owners["owner"]["points"]
    assert [(point["method"], point["response"]) for point in points] == [
        ("create_item", "helper-reference"), ("read_item", "returned"),
    ]


def test_double_inventory_keeps_domain_mocks_distinct_from_inherited_cosmos_containers():
    doubles = checker.inspect_doubles(
        "functional_tests/test_support/workflow_chat_delivery_fakes.py", """
class FakeRuntime:
    def factory(self):
        class _Store:
            def read(self):
                return {'state': 'completed'}
        return _Store()
class InheritedContainer(AtomicMemoryContainer):
    pass
""")
    assert doubles["functional_tests/test_support/workflow_chat_delivery_fakes.py::FakeRuntime"]["kind"] == "domain"
    assert doubles["functional_tests/test_support/workflow_chat_delivery_fakes.py::FakeRuntime.factory._Store"]["kind"] == "domain"
    inherited = doubles["functional_tests/test_support/workflow_chat_delivery_fakes.py::InheritedContainer"]
    assert inherited["kind"] == "class" and inherited["inherited_bases"] == ["AtomicMemoryContainer"]
    errors = checker.validate_inventory({}, {}, {}, domain_targets=["removed"])
    assert errors == ["Stale domain-double classification target: removed"]


def test_runtime_gate_selects_new_owner_and_sdk_double_evidence_automatically():
    targets = checker.runtime_test_targets({
        "owners": {
            "new": {"evidence_scope": "owner-runtime", "tests": ["functional_tests/test_new_owner.py::test_sdk"]},
            "legacy": {"evidence_scope": "sdk-api-and-source-review", "tests": ["functional_tests/test_legacy_cloud.py"]},
        },
        "doubles": {
            "new": {"classification": "sdk-default", "tests": ["functional_tests/test_new_double.py"]},
            "fault": {"classification": "fault-injection", "tests": ["functional_tests/test_fault.py"]},
        },
    })
    assert "functional_tests/test_new_owner.py::test_sdk" in targets
    assert "functional_tests/test_new_double.py" in targets
    assert "functional_tests/test_fault.py" in targets
    assert "functional_tests/test_legacy_cloud.py" not in targets
    assert checker.CORE_CONTRACT_TESTS <= set(targets)


def test_inventory_captures_write_only_cosmos_doubles_and_preserves_audit_metadata():
    doubles = checker.inspect_doubles("functional_tests/test_write_only.py", """
class WriteOnly:
    def create_item(self, body):
        return body
""")
    assert doubles["functional_tests/test_write_only.py::WriteOnly"]["methods"] == ["create_item"]
    refreshed = checker.refresh_inventory({}, {}, {"audit": {"scope": "reviewed"}})
    assert refreshed["audit"] == {"scope": "reviewed"}


def test_new_compatibility_seams_cannot_bypass_runtime_fault_evidence():
    boundary = {"sha256": "old", "kind": "seam", "methods": ["read_item"]}
    inventory = {
        "doubles": {"seam": {
            "boundary": boundary, "classification": "explicit-compatibility",
            "contract": "Existing explicit scenario override",
            "tests": ["functional_tests/test_cosmos_document_boundaries.py"],
        }},
        "compatibility_seam_baseline": {"seam": checker.review_digest(boundary)},
    }
    errors = checker.validate_inventory({}, {"seam": boundary}, inventory)
    assert errors == []
    changed = {**boundary, "sha256": "new"}
    errors = checker.validate_inventory({}, {"seam": changed}, inventory)
    assert any("Stale compatibility seam" in error for error in errors)
    assert any("runtime fault-injection evidence" in error for error in errors)


def test_inventory_captures_inline_cosmos_containers_inside_subprocess_probes():
    source = "PROBE = '''class OfflineContainer:\\n    def read_item(self, item):\\n        return {}\\n'''"
    doubles = checker.inspect_doubles("functional_tests/test_probe.py", source)
    key = "functional_tests/test_probe.py::embedded-PROBE::OfflineContainer"
    assert doubles[key]["methods"] == ["read_item"]
    assert doubles[key]["embedded_source_sha256"]


def test_network_guard_blocks_external_calls_but_allows_stdlib_socketpair():
    import socket
    from unittest.mock import patch

    from test_support import cosmos_network_guard

    with patch.object(socket.socket, "connect", cosmos_network_guard._connect):
        with socket.socket() as connection:
            with pytest.raises(AssertionError, match="cannot access the network"):
                connection.connect(("127.0.0.1", 443))
        left, right = cosmos_network_guard._socketpair()
        try:
            left.send(b"x")
            received = right.recv(1)
            assert received == b"x"
        finally:
            left.close()
            right.close()
    with pytest.raises(AssertionError, match="cannot access the network"):
        cosmos_network_guard._blocked()
