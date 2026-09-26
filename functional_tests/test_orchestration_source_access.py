# test_orchestration_source_access.py
"""
Strict current-source authority errors for retained orchestration results.
Version: 0.261.141
Implemented in: 0.261.127
Authority check reason codes added in: 0.261.141

Exercise real screening, source resolution, retained facade and alias discovery.
Only external storage, membership, model and telemetry I/O are doubled.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import importlib
import json
from pathlib import Path
import socket
import subprocess
import sys
from threading import Event
from types import SimpleNamespace

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError, ServiceRequestError, ServiceResponseError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from flask import Flask
import pytest
from requests.exceptions import Timeout as RequestsTimeout

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

# Application imports follow the standalone test path bootstrap.
from content_screening import access
from content_screening.contracts import (
    DocumentHeldError,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    SourceAuthorityUnavailableError,
    SourceAuthorityUnverifiedError,
)
from functions_mixed_source_orchestration import MixedSourceCancellationError, resolve_authorized_source_manifest
from functions_orchestration_services import discover_result_aliases
from functions_orchestration_source_access import (
    read_orchestration_source_metadata,
    resolve_orchestration_source_manifest,
)
from test_content_screening_access import ScreeningAccessFixture, fake_module
from test_support.orchestration_results import ResultFixture


def no_network(*args, **kwargs):
    raise AssertionError("Source-authority tests cannot contact external services.")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    telemetry = importlib.import_module("functions_appinsights")
    monkeypatch.setattr(telemetry, "log_event", lambda *args, **kwargs: None)


class AuthorityContainer:
    def __init__(self, documents):
        self.documents = documents
        self.failure = None
        self.reads = []

    def read_item(self, item, partition_key, **kwargs):
        self.reads.append((item, partition_key))
        if self.failure is not None:
            raise self.failure
        if item not in self.documents:
            raise CosmosResourceNotFoundError(status_code=404, message="PRIVATE provider record lookup.")
        return deepcopy(self.documents[item])

    def query_items(self, **kwargs):
        if self.failure is not None:
            raise self.failure
        return list(deepcopy(self.documents).values())


@contextmanager
def authority_runtime(monkeypatch, *, with_search=False):
    fixture = ScreeningAccessFixture()
    before = dict(sys.modules)
    fixture.setUp()
    patcher = pytest.MonkeyPatch()
    try:
        for attribute, resource in (
            ("personal", "cosmos_user_documents_container"),
            ("groups", "cosmos_group_documents_container"),
            ("public", "cosmos_public_documents_container"),
            ("scans", "cosmos_content_screening_container"),
            ("conversations", "cosmos_conversations_container"),
            ("messages", "cosmos_messages_container"),
        ):
            container = AuthorityContainer(getattr(fixture, attribute).documents)
            setattr(fixture, attribute, container)
            setattr(fixture.config, resource, container)
        search = None
        if with_search:
            patcher.setitem(sys.modules, "azure.core", before["azure.core"])
            fixture.config.cognitive_services_scope = "https://cognitiveservices.azure.com/.default"
            fixture.modules["functions_group"].get_user_groups = lambda user_id: [
                {"id": group_id} for actor, group_id in fixture.memberships if actor == user_id
            ]
            public = fixture.modules["functions_public_workspaces"]
            public.get_user_visible_public_workspace_ids_from_settings = lambda user_id: list(fixture.workspace_ids)
            public.get_user_visible_public_workspace_docs = lambda user_id: [{"id": key} for key in fixture.workspace_ids]
            settings = fixture.modules["functions_settings"]
            settings.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
            documents = fixture.modules["functions_documents"]
            documents.get_document_record = lambda **kwargs: None
            documents.get_ordered_document_chunks = no_network
            # Source normalization is real; unrelated embedding/cache/provider I/O is not used.
            patcher.setitem(sys.modules, "functions_content", fake_module("functions_content"))
            patcher.setitem(sys.modules, "utils_cache", fake_module(
                "utils_cache", generate_search_cache_key=no_network, get_cached_search_results=no_network,
                cache_search_results=no_network, DEBUG_ENABLED=False,
            ))
            patcher.delitem(sys.modules, "functions_search_service", raising=False)
            search = importlib.import_module("functions_search_service")
        yield SimpleNamespace(fixture=fixture, search=search)
    finally:
        patcher.undo()
        fixture.doCleanups()
        for name, module in list(sys.modules.items()):
            filename = getattr(module, "__file__", "") or ""
            if name not in before and str(APP).lower() in filename.lower():
                sys.modules.pop(name, None)


@pytest.mark.parametrize("failure", [
    TimeoutError("PRIVATE timeout"),
    ConnectionError("PRIVATE connection"),
    ServiceRequestError("PRIVATE request"),
    ServiceResponseError("PRIVATE response"),
    RequestsTimeout("PRIVATE requests timeout"),
    HttpResponseError(message="PRIVATE throttle", response=SimpleNamespace(status_code=429, reason="Busy", headers={})),
    CosmosHttpResponseError(status_code=503, message="PRIVATE Cosmos outage"),
])
def test_strict_metadata_io_is_retryable_unverified_not_a_hold(failure):
    def reader(**kwargs):
        raise failure

    with pytest.raises(SourceAuthorityUnavailableError) as raised:
        access.assert_document_available("document-1", "user-1", metadata_reader=reader, strict_errors=True)
    error = raised.value
    assert error.code == "source_authority_unavailable" and error.retryable is True
    assert not isinstance(error, DocumentHeldError) and "PRIVATE" not in str(error)


def test_runtime_failure_uses_owner_logging_without_provider_diagnostics(monkeypatch):
    events = []
    telemetry = importlib.import_module("functions_appinsights")
    monkeypatch.setattr(telemetry, "log_event", lambda message, **kwargs: events.append((message, kwargs)))

    def reader(**kwargs):
        raise TimeoutError("PRIVATE provider endpoint and credentials")

    with pytest.raises(SourceAuthorityUnavailableError):
        access.assert_document_available("document-1", "user-1", metadata_reader=reader, strict_errors=True)
    assert events and all(event[1]["extra"]["code"] == "source_authority_unavailable" for event in events)
    assert "PRIVATE" not in json.dumps(events)


@pytest.mark.parametrize("failure_type", [ScreeningError, ScreeningConfigurationError])
def test_original_screening_service_error_is_preserved_and_fences_caught_fallback(failure_type):
    failure = failure_type("PRIVATE screening diagnostics.")

    def reader(**kwargs):
        raise failure

    app = Flask(__name__)
    calls = []
    guarded = access.guard_model_callable(lambda: calls.append("model"), [], "user-1")
    with app.test_request_context():
        with pytest.raises(failure_type) as raised:
            access.assert_document_available("document-1", "user-1", metadata_reader=reader, strict_errors=True)
        with pytest.raises(failure_type):
            guarded()
    assert raised.value is failure and calls == []
    payload = {"code": failure.code, "message": failure.public_message, "retryable": failure.retryable}
    assert "PRIVATE" not in json.dumps(payload)


@pytest.mark.parametrize("value", [None, [], {}, {"id": "different"}, {"id": "document-1", "content_screening": []}])
def test_malformed_current_authority_is_nonretryable_unverified(value):
    with pytest.raises(SourceAuthorityUnverifiedError) as raised:
        access.assert_document_available(
            "document-1", "user-1", metadata_reader=lambda **kwargs: value, strict_errors=True,
        )
    assert raised.value.retryable is False and raised.value.code == "source_authority_unverified"


@pytest.mark.parametrize("field,value", [
    ("state", "unknown"), ("scan_id", {}), ("content_fingerprint", True),
    ("source_revision", True), ("source_revision", None), ("source_revision", float("nan")),
])
def test_malformed_available_screening_marker_is_unverified_not_a_genuine_hold(monkeypatch, field, value):
    with authority_runtime(monkeypatch) as runtime:
        runtime.fixture.document["content_screening"][field] = value
        with pytest.raises(SourceAuthorityUnverifiedError):
            read_orchestration_source_metadata("document-1", "user-1")
        with pytest.raises(DocumentHeldError):
            access.assert_document_available("document-1", "user-1")


@pytest.mark.parametrize("failure", [
    ValueError("PRIVATE malformed metadata"), RuntimeError("PRIVATE configuration"),
    KeyError("PRIVATE missing authority field"),
    CosmosHttpResponseError(status_code=403, message="PRIVATE backend credential configuration"),
    CosmosHttpResponseError(status_code=401, message="PRIVATE backend credentials"),
])
def test_nontransient_authority_failure_is_not_a_denial_or_retryable_success(failure):
    def reader(**kwargs):
        raise failure

    with pytest.raises(SourceAuthorityUnverifiedError) as raised:
        access.assert_document_available("document-1", "user-1", metadata_reader=reader, strict_errors=True)
    assert raised.value.retryable is False and "PRIVATE" not in str(raised.value)


@pytest.mark.parametrize("failure", [
    PermissionError("Denied"), LookupError("Missing"), DocumentHeldError(), ScreeningConflictError(),
])
def test_known_unavailable_outcomes_still_fail_closed(failure):
    def reader(**kwargs):
        raise failure

    with pytest.raises(type(failure)) as raised:
        access.assert_document_available("document-1", "user-1", metadata_reader=reader, strict_errors=True)
    assert raised.value is failure


def test_strict_opt_in_does_not_change_or_leak_into_legacy_default():
    def reader(**kwargs):
        raise TimeoutError("PRIVATE authority outage")

    with pytest.raises(DocumentHeldError) as legacy:
        access.assert_document_available("document-1", "user-1", metadata_reader=reader)
    with pytest.raises(SourceAuthorityUnavailableError):
        access.assert_document_available("document-1", "user-1", metadata_reader=reader, strict_errors=True)
    enabled = access.strict_source_authority_enabled()
    with pytest.raises(DocumentHeldError):
        access.assert_document_available("document-1", "user-1", metadata_reader=reader)
    assert enabled is False and "PRIVATE" not in str(legacy.value)


def test_headless_owner_scope_keeps_first_failure_when_caught_and_restores_context():
    failures = [TimeoutError("PRIVATE first outage"), PermissionError("Later denial")]
    calls = []
    guarded = access.guard_model_callable(lambda: calls.append("model"), [], "user-1")
    with access.strict_source_authority():
        for failure in failures:
            def reader(**kwargs):
                raise failure

            with pytest.raises((SourceAuthorityUnavailableError, PermissionError)):
                access.assert_document_available("document-1", "user-1", metadata_reader=reader)
        with pytest.raises(SourceAuthorityUnavailableError):
            guarded()
    enabled = access.strict_source_authority_enabled()
    guarded()
    assert enabled is False and calls == ["model"]


@pytest.mark.parametrize("evidence", [False, True])
def test_malformed_source_arguments_cannot_escape_a_caught_error_model_fence(evidence):
    source = {"document_id": "document-1", "screening_provenance": {"document_id": "different"}}
    calls = []
    guarded = access.guard_model_callable(lambda: calls.append("model"), [], "user-1")
    app = Flask(__name__)
    with app.test_request_context(), access.strict_source_authority():
        with pytest.raises(SourceAuthorityUnverifiedError):
            if evidence:
                access.assert_evidence_available([source], "user-1")
            else:
                access.assert_document_available(source, "user-1", metadata_reader=no_network)
        with pytest.raises(SourceAuthorityUnverifiedError):
            guarded()
    assert calls == []


def _authority_events(monkeypatch):
    events = []
    telemetry = importlib.import_module("functions_appinsights")
    monkeypatch.setattr(telemetry, "log_event", lambda message, **kwargs: events.append(dict(kwargs.get("extra") or {})))
    return events


@pytest.mark.parametrize("source,value,reason", [
    ({"document_id": "document-1", "screening_provenance": {"document_id": "PRIVATE-other"}}, None, "provenance_mismatch"),
    ({"document_id": "   "}, None, "document_id_invalid"),
    ("document-1", {"id": "PRIVATE-other"}, "document_record_invalid"),
    ("document-1", {"id": "document-1", "content_screening": []}, "screening_marker_invalid"),
    ("document-1", {"id": "document-1", "content_screening": {"state": "PRIVATE-state"}}, "screening_state_unknown"),
])
def test_malformed_authority_logs_which_check_failed_without_values(monkeypatch, source, value, reason):
    events = _authority_events(monkeypatch)
    reader = no_network if value is None else (lambda **kwargs: deepcopy(value))
    with pytest.raises(SourceAuthorityUnverifiedError) as raised:
        access.assert_document_available(source, "user-1", metadata_reader=reader, strict_errors=True)
    assert raised.value.authority_reason == reason
    assert events and all(event["authority_reason"] == reason for event in events)
    assert all(event["failure_code"] == "source_authority_unverified" for event in events)
    assert "PRIVATE" not in json.dumps(events)


def test_legacy_malformed_authority_stays_a_quiet_hold(monkeypatch):
    events = _authority_events(monkeypatch)
    source = {"document_id": "document-1", "screening_provenance": {"document_id": "other"}}
    with pytest.raises(DocumentHeldError) as raised:
        access.assert_document_available(source, "user-1", metadata_reader=no_network)
    assert events == [] and getattr(raised.value, "authority_reason", None) is None


def test_io_authority_failures_log_their_code_without_a_check_reason(monkeypatch):
    events = _authority_events(monkeypatch)

    def reader(**kwargs):
        raise TimeoutError("PRIVATE provider endpoint")

    with pytest.raises(SourceAuthorityUnavailableError):
        access.assert_document_available("document-1", "user-1", metadata_reader=reader, strict_errors=True)
    assert events and all(event["failure_code"] == "source_authority_unavailable" for event in events)
    assert all("authority_reason" not in event for event in events)


def test_malformed_manifest_context_logs_its_check(monkeypatch):
    events = _authority_events(monkeypatch)
    malformed = {"scope": "personal", "document": {"id": "PRIVATE-other"}}
    with pytest.raises(SourceAuthorityUnverifiedError) as raised:
        resolve_orchestration_source_manifest(["document-1"], "user-1", context_resolver=lambda **kwargs: malformed)
    assert raised.value.authority_reason == "manifest_context_invalid"
    assert events and events[0]["authority_reason"] == "manifest_context_invalid"
    assert "PRIVATE" not in json.dumps(events)


def test_concurrent_headless_authority_scopes_do_not_share_caught_failures():
    failed = Event()
    healthy = Event()
    calls = []

    def failed_operation():
        with access.strict_source_authority():
            with pytest.raises(SourceAuthorityUnavailableError):
                access.raise_source_authority_error(TimeoutError("PRIVATE authority"))
            failed.set()
            if not healthy.wait(timeout=5):
                raise AssertionError("The independent healthy operation did not finish.")
            with pytest.raises(SourceAuthorityUnavailableError):
                access.assert_current_request_sources_available()

    def healthy_operation():
        if not failed.wait(timeout=5):
            raise AssertionError("The independent failed operation did not start.")
        try:
            with access.strict_source_authority():
                guarded = access.guard_model_callable(lambda: calls.append("healthy"), [], "other-user")
                guarded()
        finally:
            healthy.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        failed_future = pool.submit(failed_operation)
        healthy_future = pool.submit(healthy_operation)
        failed_future.result(timeout=10)
        healthy_future.result(timeout=10)
    assert calls == ["healthy"]


def test_real_missing_error_is_not_guessed_from_status_or_exception_cause():
    class OtherBackendError(Exception):
        status_code = 404

    failure = OtherBackendError("PRIVATE unrelated error")
    failure.__cause__ = CosmosResourceNotFoundError(status_code=404, message="PRIVATE cause")
    with access.strict_source_authority():
        with pytest.raises(SourceAuthorityUnverifiedError):
            access.raise_source_authority_error(failure)
    with access.strict_source_authority():
        with pytest.raises(LookupError) as missing:
            access.raise_source_authority_error(ResourceNotFoundError("PRIVATE missing document"))
    assert "PRIVATE" not in str(missing.value)


@pytest.mark.parametrize("resource", ["personal", "scans"])
def test_real_current_document_and_release_proof_outages_remain_typed(monkeypatch, resource):
    with authority_runtime(monkeypatch) as runtime:
        fixture = runtime.fixture
        getattr(fixture, resource).failure = CosmosHttpResponseError(status_code=503, message="PRIVATE storage outage")
        with pytest.raises(SourceAuthorityUnavailableError):
            read_orchestration_source_metadata("document-1", "user-1")
        with pytest.raises(DocumentHeldError):
            access.assert_document_available("document-1", "user-1")


def test_real_current_hold_missing_and_revision_are_unavailable(monkeypatch):
    with authority_runtime(monkeypatch) as runtime:
        fixture = runtime.fixture
        source = deepcopy(fixture.document)
        source["version"] = 1
        with pytest.raises(ScreeningConflictError):
            access.assert_document_available(source, "user-1", strict_errors=True)
        fixture.document["content_screening"]["state"] = "pending_review"
        with pytest.raises(DocumentHeldError):
            read_orchestration_source_metadata("document-1", "user-1")
        with pytest.raises(LookupError):
            read_orchestration_source_metadata("missing", "user-1")


def test_current_group_membership_and_public_scope_are_rechecked(monkeypatch):
    with authority_runtime(monkeypatch) as runtime:
        fixture = runtime.fixture
        group = {**deepcopy(fixture.document), "group_id": "group-1"}
        fixture.groups.documents["document-1"] = group
        fixture.seed_release(group)
        allowed = read_orchestration_source_metadata("document-1", "user-1", group_id="group-1")
        fixture.memberships.clear()
        with pytest.raises(PermissionError):
            read_orchestration_source_metadata("document-1", "user-1", group_id="group-1")
        public = {**deepcopy(fixture.document), "public_workspace_id": "workspace-1"}
        fixture.public.documents["document-1"] = public
        fixture.seed_release(public)
        public_allowed = read_orchestration_source_metadata("document-1", "user-1", public_workspace_id="workspace-1")
        with pytest.raises(PermissionError):
            read_orchestration_source_metadata("document-1", "user-1", public_workspace_id="other-workspace")
        fixture.workspace_ids.clear()
        with pytest.raises(PermissionError):
            read_orchestration_source_metadata("document-1", "user-1", public_workspace_id="workspace-1")
        assert allowed["group_id"] == "group-1" and public_allowed["public_workspace_id"] == "workspace-1"


@pytest.mark.parametrize("scope", ["group", "public"])
@pytest.mark.parametrize("malformed", [False, True])
def test_current_membership_and_workspace_authority_failures_are_not_revocation(monkeypatch, scope, malformed):
    with authority_runtime(monkeypatch) as runtime:
        fixture = runtime.fixture
        document = {**deepcopy(fixture.document), f"{scope if scope == 'group' else 'public_workspace'}_id": f"{scope}-1"}
        container = fixture.groups if scope == "group" else fixture.public
        container.documents["document-1"] = document
        fixture.seed_release(document)

        def unavailable(*args, **kwargs):
            if malformed:
                if scope == "public":
                    return {"id": "different-workspace"}
                raise ValueError("PRIVATE malformed membership")
            raise CosmosHttpResponseError(status_code=503, message="PRIVATE scope authority")

        if scope == "group":
            monkeypatch.setattr(fixture.modules["functions_group"], "assert_group_role", unavailable)
            arguments = {"group_id": "group-1"}
        else:
            monkeypatch.setattr(fixture.modules["functions_public_workspaces"], "find_public_workspace_by_id", unavailable)
            arguments = {"public_workspace_id": "public-1"}
        expected = SourceAuthorityUnverifiedError if malformed else SourceAuthorityUnavailableError
        with pytest.raises(expected):
            read_orchestration_source_metadata("document-1", "user-1", **arguments)


def test_context_resolver_outage_is_only_suppressed_by_legacy_default():
    def failed(**kwargs):
        raise CosmosHttpResponseError(status_code=503, message="PRIVATE context authority")

    legacy = resolve_authorized_source_manifest(["document-1"], "user-1", context_resolver=failed)
    with pytest.raises(SourceAuthorityUnavailableError):
        resolve_orchestration_source_manifest(["document-1"], "user-1", context_resolver=failed)
    assert legacy[0]["authorization_status"] == "unresolved"


@pytest.mark.parametrize("malformed", [[], {}, {"document": {}}, {"scope": "personal", "document": {"id": "other"}}])
def test_malformed_context_authority_is_not_a_missing_source(malformed):
    with pytest.raises(SourceAuthorityUnverifiedError):
        resolve_orchestration_source_manifest(["document-1"], "user-1", context_resolver=lambda **kwargs: malformed)


def test_real_mixed_search_source_seam_uses_fresh_metadata_not_legacy_fallback(monkeypatch):
    with authority_runtime(monkeypatch, with_search=True) as runtime:
        fixture = runtime.fixture
        resolved = resolve_orchestration_source_manifest(["document-1"], "user-1", doc_scope="personal")
        assert resolved[0]["authorization_status"] == "authorized" and resolved[0]["source_version"] == 2
        fixture.personal.failure = CosmosHttpResponseError(status_code=503, message="PRIVATE authority")
        with pytest.raises(SourceAuthorityUnavailableError):
            resolve_orchestration_source_manifest(["document-1"], "user-1", doc_scope="personal")
        legacy = resolve_authorized_source_manifest(["document-1"], "user-1", doc_scope="personal")
        assert legacy[0]["authorization_status"] == "unresolved"


def test_real_scope_probe_can_skip_missing_personal_record_without_poisoning_group_success(monkeypatch):
    with authority_runtime(monkeypatch, with_search=True) as runtime:
        fixture = runtime.fixture
        group = {**deepcopy(fixture.document), "group_id": "group-1"}
        fixture.personal.documents.clear()
        fixture.groups.documents["document-1"] = group
        fixture.seed_release(group)
        with access.strict_source_authority():
            manifest = resolve_orchestration_source_manifest(
                ["document-1"], "user-1", active_group_ids=["group-1"], doc_scope="all",
            )
            access.assert_current_request_sources_available("user-1")
        assert manifest[0]["scope"] == "group" and manifest[0]["scope_id"] == "group-1"
        assert fixture.personal.reads and fixture.groups.reads


@pytest.mark.parametrize("scope", ["group", "public"])
def test_real_scope_enumeration_outages_do_not_turn_requested_sources_into_unresolved(monkeypatch, scope):
    with authority_runtime(monkeypatch, with_search=True) as runtime:
        def failed(user_id):
            raise ServiceRequestError("PRIVATE membership/visibility outage")

        target = "get_user_groups" if scope == "group" else "get_user_visible_public_workspace_ids_from_settings"
        monkeypatch.setattr(runtime.search, target, failed)
        arguments = {"active_group_ids": ["group-1"]} if scope == "group" else {"active_public_workspace_ids": ["workspace-1"]}
        with pytest.raises(SourceAuthorityUnavailableError):
            resolve_orchestration_source_manifest(["document-1"], "user-1", doc_scope=scope, **arguments)
        legacy = resolve_authorized_source_manifest(["document-1"], "user-1", doc_scope=scope, **arguments)
        assert legacy[0]["authorization_status"] == "unresolved"


@pytest.mark.parametrize("resource", ["conversations", "messages"])
def test_real_chat_source_metadata_outages_are_not_missing_uploads(monkeypatch, resource):
    with authority_runtime(monkeypatch, with_search=True) as runtime:
        getattr(runtime.fixture, resource).failure = TimeoutError("PRIVATE chat authority outage")
        with pytest.raises(SourceAuthorityUnavailableError):
            resolve_orchestration_source_manifest(
                ["upload-1"], "user-1", doc_scope="personal", conversation_id="conversation-1",
            )


@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", {"private": "invalid"}), ("version", float("nan")),
    ("_etag", ["invalid"]), ("updated_at", {"invalid": "revision"}),
])
def test_real_source_manifest_rejects_malformed_revision_authority(monkeypatch, field, value):
    with authority_runtime(monkeypatch, with_search=True) as runtime:
        document = runtime.fixture.document
        document.pop("content_screening")
        document[field] = value
        with pytest.raises(SourceAuthorityUnverifiedError):
            resolve_orchestration_source_manifest(["document-1"], "user-1", doc_scope="personal")


def test_strict_manifest_cancellation_is_not_reclassified_as_authority_error():
    with pytest.raises(MixedSourceCancellationError):
        resolve_orchestration_source_manifest(
            ["document-1"], "user-1", context_resolver=no_network, cancel_requested=lambda: True,
        )


@pytest.mark.parametrize("failure_type", [SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError])
def test_real_retained_facade_and_root_discovery_propagate_operational_errors(monkeypatch, failure_type):
    fixture = ResultFixture()
    task = fixture.save()
    record = fixture.runs["run-1"]
    record["plan"]["planner_contract_version"] = 2
    record["task_results"] = {"analyze": task.to_dict()}

    def unavailable(**kwargs):
        raise failure_type()

    monkeypatch.setattr(fixture, "metadata", unavailable)
    reopened = fixture.restart()
    with pytest.raises(failure_type):
        discover_result_aliases([deepcopy(record)], reopened)


@pytest.mark.parametrize("malformation", ["missing", "order", "scope", "status", "version"])
def test_retained_facade_rejects_malformed_fresh_resolver_authority(monkeypatch, malformation):
    fixture = ResultFixture()
    task = fixture.save()
    fresh = fixture.resolve(["document-1"])
    if malformation == "missing":
        fresh = []
    elif malformation == "order":
        fresh[0]["document_id"] = "different"
    elif malformation == "scope":
        fresh[0]["scope_id"] = []
    elif malformation == "status":
        fresh[0]["authorization_status"] = "unknown"
    else:
        fresh[0]["source_version"] = {"not": "a revision"}
    monkeypatch.setattr(fixture, "resolve", lambda *args, **kwargs: deepcopy(fresh))
    reopened = fixture.restart()
    with pytest.raises(SourceAuthorityUnverifiedError):
        reopened.open_result(task.output("findings"))


def test_retained_reader_rechecks_outage_then_recovers_without_overwriting_saved_result(monkeypatch):
    fixture = ResultFixture()
    task = fixture.save()
    stored = deepcopy(fixture.container.items)
    original_metadata = fixture.metadata

    def failed(**kwargs):
        raise CosmosHttpResponseError(status_code=503, message="PRIVATE metadata outage")

    monkeypatch.setattr(fixture, "metadata", failed)
    reader_service = fixture.restart()
    with pytest.raises(SourceAuthorityUnavailableError):
        reader_service.open_result(task.output("findings"))
    monkeypatch.setattr(fixture, "metadata", original_metadata)
    reader = fixture.restart().open_result(task.output("findings"))
    rows = list(reader.iter_records())
    assert len(rows) == 3 and rows[-1]["id"] == "last" and fixture.container.items == stored


@pytest.mark.parametrize("first", ["content_screening.access", "functions_orchestration_source_access", "functions_orchestration_results"])
@pytest.mark.parametrize("optimized", [False, True])
def test_real_cold_imports_do_not_bootstrap_or_contact_authority(first, optimized):
    script = """
import builtins, importlib, socket, sys
from unittest.mock import patch
def blocked(*args, **kwargs):
    raise RuntimeError('Network forbidden during import.')
socket.socket.connect = blocked
socket.create_connection = blocked
sys.path.insert(0, sys.argv[1])
owners = {'config', 'functions_settings', 'functions_appinsights', 'route_backend_chats'}
real_import = builtins.__import__
def owner_free_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in owners:
        raise RuntimeError('Source-access import reached its owner: ' + name)
    return real_import(name, globals, locals, fromlist, level)
with patch.object(builtins, '__import__', owner_free_import):
    importlib.import_module(sys.argv[2])
    access = importlib.import_module('content_screening.access')
    importlib.import_module('functions_orchestration_source_access')
    importlib.import_module('functions_orchestration_results')
if owners.intersection(sys.modules):
    raise RuntimeError('Source-access imports initialized an application owner.')
contracts = importlib.import_module('content_screening.contracts')
calls = []
def failed(**kwargs):
    raise TimeoutError('Private metadata outage.')
with access.strict_source_authority():
    try:
        access.assert_document_available('doc', 'owner', metadata_reader=failed)
    except contracts.SourceAuthorityUnavailableError as error:
        if error.code != 'source_authority_unavailable' or error.retryable is not True:
            raise RuntimeError('Incorrect source authority error contract.')
    else:
        raise RuntimeError('Authority failure became success.')
    guarded = access.guard_model_callable(lambda: calls.append('model'), [], 'owner')
    try:
        guarded()
    except contracts.SourceAuthorityUnavailableError:
        pass
    else:
        raise RuntimeError('Caught authority failure lost the model fence.')
if calls:
    raise RuntimeError('Unauthorized fallback reached a model.')
if access.strict_source_authority_enabled() or 'config' in sys.modules or 'route_backend_chats' in sys.modules:
    raise RuntimeError('Source access crossed the bootstrap/route boundary.')
"""
    completed = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-c", script, str(APP), first],
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
