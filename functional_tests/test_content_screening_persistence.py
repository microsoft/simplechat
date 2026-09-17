# test_content_screening_persistence.py
"""
Behavioral tests for private screening persistence without live Azure resources.
Version: 0.261.106
Implemented in: 0.261.106

Exercises exact-scope Cosmos reads, CAS writes, cursor binding, immutable
segmented blobs, conditional reads, and revision-confined deletion.
"""

import copy
import hashlib
import io
import json
import re
import sys
import threading
import types
from pathlib import Path

import pytest
from azure.core import MatchConditions


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from content_screening import storage as storage_module
from content_screening.contracts import ScreeningConflictError, ScreeningConfigurationError, ScreeningValidationError, Subject
from content_screening.repository import ScreeningRepository
from content_screening.storage import ScreeningStorage


class FakeSdkError(RuntimeError):
    def __init__(self, status_code):
        super().__init__("private-provider-error-canary")
        self.status_code = status_code


class FakePages:
    def __init__(self, records, size, continuation_token=None):
        self.records = sorted(copy.deepcopy(records), key=lambda item: (item["id"], item.get("partition_key", item["id"])))
        if continuation_token is not None:
            cursor = tuple(continuation_token)
            self.records = [item for item in self.records if (item["id"], item.get("partition_key", item["id"])) > cursor]
        self.size = size
        self.continuation_token = None

    def __iter__(self):
        return self

    def __next__(self):
        if not self.records:
            raise StopIteration
        items, self.records = self.records[:self.size], self.records[self.size:]
        last = items[-1]
        self.continuation_token = [last["id"], last.get("partition_key", last["id"])] if self.records else None
        return iter(items)


class FakeQuery:
    def __init__(self, records, size):
        self.records, self.size = copy.deepcopy(records), size

    def by_page(self, continuation_token=None):
        return FakePages(self.records, self.size, continuation_token)

    def __iter__(self):
        return iter(copy.deepcopy(self.records))


class FakeCosmos:
    def __init__(self, documents=None, *, partition_field="partition_key"):
        self.partition_field = partition_field
        self.documents, self.queries, self.replacements = {}, [], []
        self.sequence = 0
        self.lock = threading.RLock()
        self.read_error = None
        self.before_replace = None
        for document in documents or []:
            self.create_item(document)

    def _key(self, document):
        return document["id"], document[self.partition_field]

    def create_item(self, body):
        with self.lock:
            if self._key(body) in self.documents:
                raise FakeSdkError(409)
            self.sequence += 1
            saved = {**copy.deepcopy(body), "_etag": f"etag-{self.sequence}", "_ts": self.sequence}
            self.documents[self._key(body)] = saved
            return copy.deepcopy(saved)

    def read_item(self, item, partition_key):
        with self.lock:
            if self.read_error is not None:
                raise self.read_error
            document = self.documents.get((item, partition_key))
            if document is None:
                raise FakeSdkError(404)
            return copy.deepcopy(document)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        assert match_condition is MatchConditions.IfNotModified
        with self.lock:
            if self.before_replace:
                callback, self.before_replace = self.before_replace, None
                callback()
            current = self.documents.get(self._key(body))
            if current is None:
                raise FakeSdkError(404)
            if not etag or etag != current["_etag"]:
                raise FakeSdkError(412)
            self.sequence += 1
            self.documents[self._key(body)] = {**copy.deepcopy(body), "_etag": f"etag-{self.sequence}", "_ts": self.sequence}
            self.replacements.append(copy.deepcopy(body))
            return copy.deepcopy(self.documents[self._key(body)])

    def query_items(self, query, parameters=None, max_item_count=50, **kwargs):
        with self.lock:
            self.queries.append({"query": query, "parameters": copy.deepcopy(parameters or []), **kwargs})
            records = copy.deepcopy(list(self.documents.values()))
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        for field, parameter in re.findall(r"c\.([a-zA-Z_]+) = (@[a-zA-Z_0-9]+)", query):
            records = [item for item in records if item.get(field) == values[parameter]]
        for parameter, field in re.findall(r"ARRAY_CONTAINS\((@[a-zA-Z_0-9]+), c\.([a-zA-Z_]+)\)", query):
            records = [item for item in records if item.get(field) in values[parameter]]
        for field, parameter in re.findall(r"c\.([a-zA-Z_]+) > (@[a-zA-Z_0-9]+)", query):
            records = [item for item in records if item.get(field, "") > values[parameter]]
        if "VALUE COUNT(1)" in query:
            return iter([len(records)])
        ordering = re.search(r"ORDER BY c\.([a-zA-Z_]+)", query)
        if ordering:
            records.sort(key=lambda item: item.get(ordering.group(1), ""))
        if "@page_limit" in values:
            records = records[:values["@page_limit"]]
        return FakeQuery(records, max_item_count)


class FakeBlob:
    def __init__(self, container, name):
        self.container, self.name = container, name

    def _record(self):
        if self.name not in self.container.blobs:
            raise FakeSdkError(404)
        return self.container.blobs[self.name]

    def upload_blob(self, payload, *, overwrite=False, metadata=None, content_settings=None):
        if self.container.fail_upload_name and self.name.endswith(self.container.fail_upload_name):
            self.container.fail_upload_name = None
            raise FakeSdkError(503)
        with self.container.lock:
            if self.name in self.container.blobs and not overwrite:
                raise FakeSdkError(409)
            self.container.sequence += 1
            self.container.blobs[self.name] = {
                "data": bytes(payload), "metadata": copy.deepcopy(metadata),
                "etag": f'"blob-{self.container.sequence}"', "content_settings": content_settings,
            }
            return {"etag": self._record()["etag"]}

    def get_blob_properties(self):
        record = self._record()
        return {"name": self.name, "size": len(record["data"]), "etag": record["etag"], "metadata": copy.deepcopy(record["metadata"])}

    def download_blob(self, *, etag, match_condition, offset=0, length=None, max_concurrency=1):
        assert match_condition is MatchConditions.IfNotModified
        assert max_concurrency == 1
        record = self._record()
        if record["etag"] != etag:
            raise FakeSdkError(412)
        self.container.reads.append({"name": self.name, "etag": etag, "length": length})
        data = record["data"][offset:offset + length if length is not None else None]
        return types.SimpleNamespace(readall=lambda: data)

    def delete_blob(self, *, etag, match_condition, **kwargs):
        assert match_condition is MatchConditions.IfNotModified
        if self._record()["etag"] != etag:
            raise FakeSdkError(412)
        self.container.deleted.append(self.name)
        del self.container.blobs[self.name]


class FakeBlobContainer:
    def __init__(self):
        self.blobs, self.reads, self.deleted = {}, [], []
        self.sequence = 0
        self.exists, self.public_access, self.fail_upload_name = False, None, None
        self.lock = threading.RLock()

    def get_container_properties(self):
        if not self.exists:
            raise FakeSdkError(404)
        return {"public_access": self.public_access}

    def create_container(self):
        if self.exists:
            raise FakeSdkError(409)
        self.exists = True

    def get_blob_client(self, name):
        return FakeBlob(self, name)

    def list_blobs(self, name_starts_with, **kwargs):
        for name in sorted(self.blobs):
            if name.startswith(name_starts_with):
                yield self.get_blob_client(name).get_blob_properties()


class FakeBlobService:
    def __init__(self):
        self.containers = {}

    def get_container_client(self, name):
        return self.containers.setdefault(name, FakeBlobContainer())

    def get_blob_client(self, *, container, blob):
        return self.get_container_client(container).get_blob_client(blob)


@pytest.fixture
def persistence():
    metadata = FakeCosmos()
    personal = FakeCosmos([
        {"id": "doc", "user_id": "owner", "version": 2, "file_name": "private.txt", "server_field": "keep"},
    ], partition_field="id")
    repository = ScreeningRepository(metadata, {"personal": personal})
    subject = Subject("personal", "owner", "doc", "2")
    service = FakeBlobService()
    return repository, subject, ScreeningStorage(service), service


def test_construction_has_no_configuration_or_network_side_effects(monkeypatch):
    class ForbiddenConfiguration:
        def __getattr__(self, _name):
            raise AssertionError("Configuration was accessed during construction.")

    monkeypatch.setitem(sys.modules, "config", ForbiddenConfiguration())
    ScreeningRepository()
    ScreeningStorage()


def test_explicit_activation_uses_only_the_fresh_client_and_private_container(monkeypatch):
    monkeypatch.setitem(sys.modules, "config", None)
    container = FakeBlobContainer()
    operations, requested_names = [], []

    def probe():
        operations.append("probe")
        return FakeBlobContainer.get_container_properties(container)

    def create():
        operations.append("create")
        return FakeBlobContainer.create_container(container)

    monkeypatch.setattr(container, "get_container_properties", probe)
    monkeypatch.setattr(container, "create_container", create)
    client = types.SimpleNamespace(
        get_container_client=lambda name: requested_names.append(name) or container,
    )
    storage = ScreeningStorage(client=client)
    assert not operations and not requested_names
    assert storage.validate_connection() == {"configured": True, "private": True}
    assert requested_names == ["content-screening"]
    assert operations == ["probe", "create", "probe"]
    assert container.blobs == {}
    assert storage.validate_connection() == {"configured": True, "private": True}
    assert operations == ["probe", "create", "probe", "probe"]
    container.public_access = "blob"
    with pytest.raises(ScreeningConfigurationError):
        storage.validate_connection()
    assert operations[-1] == "probe" and operations.count("create") == 1


@pytest.mark.parametrize("public_access", [None, "container"])
def test_activation_creation_race_rechecks_container_privacy(monkeypatch, public_access):
    container = FakeBlobContainer()

    def concurrent_creation():
        container.exists = True
        container.public_access = public_access
        raise FakeSdkError(409)

    monkeypatch.setattr(container, "create_container", concurrent_creation)
    storage = ScreeningStorage(client=types.SimpleNamespace(get_container_client=lambda _name: container))
    if public_access:
        with pytest.raises(ScreeningConfigurationError):
            storage.validate_connection()
    else:
        assert storage.validate_connection() == {"configured": True, "private": True}
    assert container.blobs == {}


def test_activation_does_not_create_after_a_permission_failure(monkeypatch):
    container = FakeBlobContainer()
    calls = []

    def forbidden():
        raise FakeSdkError(403)

    monkeypatch.setattr(container, "get_container_properties", forbidden)
    monkeypatch.setattr(container, "create_container", lambda: calls.append("create"))
    storage = ScreeningStorage(client=types.SimpleNamespace(get_container_client=lambda _name: container))
    with pytest.raises(FakeSdkError) as failure:
        storage.validate_connection()
    assert failure.value.status_code == 403
    assert calls == [] and storage._verified_container is None


def test_only_missing_records_return_none(persistence):
    repository, *_ = persistence
    assert repository.get("absent", "absent") is None
    error = FakeSdkError(403)
    repository.container.read_error = error
    with pytest.raises(FakeSdkError) as failure:
        repository.get("forbidden", "forbidden")
    assert failure.value is error


def test_scope_and_revision_are_verified_before_document_changes(persistence):
    repository, subject, *_ = persistence
    for invalid in (Subject("personal", "other-owner", "doc", "2"), Subject("personal", "owner", "doc", "1")):
        with pytest.raises(ScreeningConflictError):
            repository.read_document(invalid)
    document = repository.read_document(subject)
    with pytest.raises(ScreeningValidationError):
        repository.update_document(subject, {"user_id": "other-owner"}, etag=document["_etag"])
    assert not repository.document_container("personal").replacements


def test_document_cas_preserves_server_fields_and_rejects_races(persistence):
    repository, subject, *_ = persistence
    document = repository.read_document(subject)
    saved = repository.update_document(subject, {"content_screening": {"state": "pending_scan"}}, etag=document["_etag"])
    assert saved["server_field"] == "keep"
    assert saved["file_name"] == "private.txt"
    with pytest.raises(ScreeningConflictError):
        repository.update_document(subject, {"content_screening": {"state": "cleared"}}, etag=document["_etag"])
    with pytest.raises(ScreeningConflictError):
        repository.update_document(subject, {"status": "updated"}, etag=None)
    assert repository.read_document(subject)["content_screening"]["state"] == "pending_scan"


def test_document_cas_rejects_a_change_between_read_and_replace(persistence):
    repository, subject, *_ = persistence
    document = repository.read_document(subject)
    container = repository.document_container("personal")

    def concurrent_metadata_change():
        stored = container.documents[("doc", "doc")]
        stored["server_field"] = "concurrent-update"
        stored["_etag"] = "concurrent-etag"

    container.before_replace = concurrent_metadata_change
    with pytest.raises(ScreeningConflictError):
        repository.update_document(subject, {"content_screening": {"state": "cleared"}}, etag=document["_etag"])
    latest = repository.read_document(subject)
    assert latest["server_field"] == "concurrent-update"
    assert "content_screening" not in latest


def test_record_cas_no_upserts_and_nonexpiring_holds(persistence):
    repository, subject, *_ = persistence
    record = repository.create({"id": "scan", "partition_key": "scan", "kind": "scan", "subject": subject.to_dict(), "ttl": 1})
    assert record["ttl"] == -1
    assert repository.get_scan("scan")["subject_key"] == subject.key
    with pytest.raises(ScreeningConflictError):
        repository.create(record)
    saved = repository.replace({**record, "state": "scanning"}, record["_etag"])
    with pytest.raises(ScreeningConflictError):
        repository.replace({**record, "state": "cleared"}, record["_etag"])
    assert repository.get_scan("scan")["_etag"] == saved["_etag"]


def test_policy_creates_and_updates_are_versioned_and_conditional(persistence):
    repository, *_ = persistence
    first = repository.save_policy("global", "global", {"enabled": False}, "administrator")
    assert first["partition_key"] == "policy:global:global"
    assert first["revision"] == 1
    assert first["policy"]["schema_version"] == 1
    with pytest.raises(ScreeningConflictError):
        repository.save_policy("global", "global", {"enabled": False}, "administrator")
    second = repository.save_policy("global", "global", first["policy"], "administrator", etag=first["_etag"])
    assert second["revision"] == 2
    assert second["created_at"] == first["created_at"]
    with pytest.raises(ScreeningConflictError):
        repository.save_policy("personal", "owner", {"enabled": False}, "owner", etag="not-a-version")


@pytest.mark.parametrize("scope_type", ["personal", "group", "public"])
def test_internal_workspace_policy_saves_cannot_expand_the_model_allowlist(persistence, scope_type):
    repository, *_ = persistence
    policy = {"enabled": False, "allowed_models": [{"endpoint_id": "endpoint", "model_id": "unapproved"}]}
    baseline = repository.save_policy("global", "global", policy, "administrator")
    assert baseline["policy"]["allowed_models"] == policy["allowed_models"]
    with pytest.raises(ScreeningValidationError):
        repository.save_policy(scope_type, "owner", policy, "owner")
    assert repository.get_policy(scope_type, "owner") is None
    existing = repository.save_policy(scope_type, "owner", {"enabled": False}, "owner")
    with pytest.raises(ScreeningValidationError):
        repository.save_policy(scope_type, "owner", policy, "owner", etag=existing["_etag"])
    assert repository.get_policy(scope_type, "owner") == existing


@pytest.mark.parametrize("scope_type", ["personal", "group", "public"])
def test_internal_workspace_model_selection_must_compose_with_the_baseline(persistence, scope_type):
    repository, *_ = persistence
    approved = {"endpoint_id": "endpoint", "model_id": "approved"}
    unapproved = {"endpoint_id": "endpoint", "model_id": "unapproved"}
    workspace = {
        "enabled": True,
        "ai": {"enabled": True, "model_selection": unapproved, "instructions": "Check for sensitive content."},
    }
    with pytest.raises(ScreeningValidationError):
        repository.save_policy(scope_type, "owner", workspace, "owner")
    repository.save_policy("global", "global", {"allowed_models": [approved]}, "administrator")
    with pytest.raises(ScreeningValidationError):
        repository.save_policy(scope_type, "owner", workspace, "owner")
    workspace["ai"]["model_selection"] = approved
    saved = repository.save_policy(scope_type, "owner", workspace, "owner")
    workspace["ai"]["model_selection"] = unapproved
    with pytest.raises(ScreeningValidationError):
        repository.save_policy(scope_type, "owner", workspace, "owner", etag=saved["_etag"])
    assert repository.get_policy(scope_type, "owner") == saved


def test_queries_bind_values_and_continuations_to_the_authorized_scope(persistence):
    repository, subject, *_ = persistence
    for index in range(7):
        repository.create({"id": f"scan-{index}", "partition_key": f"scan-{index}", "kind": "scan", "subject": subject.to_dict()})
    first = repository.query("scan", subject.scope_key, page_size=3)
    second = repository.query("scan", subject.scope_key, continuation=first["continuation"], page_size=3)
    final = repository.query("scan", subject.scope_key, continuation=second["continuation"], page_size=3)
    assert [len(page["items"]) for page in (first, second, final)] == [3, 3, 1]
    assert final["continuation"] is None
    with pytest.raises(ScreeningValidationError):
        repository.query("scan", "personal:other", continuation=first["continuation"], page_size=3)
    with pytest.raises(ScreeningValidationError):
        repository.query("scan", filters={"state) OR 1=1": True})
    injection = "' OR true -- private-canary"
    repository.query("scan", filters={"state": injection})
    query = repository.container.queries[-1]
    assert injection not in query["query"]
    assert any(parameter["value"] == injection for parameter in query["parameters"])
    assert repository.count("scan", subject.scope_key) == 7


def test_document_paging_includes_archived_revisions(persistence):
    repository, *_ = persistence
    documents = repository.document_container("personal")
    for index in range(8):
        documents.create_item({"id": f"old-{index}", "user_id": "owner", "version": index + 1, "is_current_version": False})
    continuation, seen = None, []
    while True:
        page = repository.query_documents("personal", "owner", continuation=continuation, page_size=2)
        seen.extend(item["id"] for item in page["items"])
        continuation = page["continuation"]
        if continuation is None:
            break
    assert len(seen) == len(set(seen)) == 9
    assert all("is_current_version" not in query["query"] for query in documents.queries)


def test_cross_partition_pages_never_replay_sdk_continuations(persistence, monkeypatch):
    repository, subject, *_ = persistence
    for partition in ("one", "two", "three"):
        repository.create({
            "id": "same-logical-id", "partition_key": partition,
            "kind": "checkpoint", "subject": subject.to_dict(),
        })

    def reject_rebuilt_pager(self, continuation_token=None):
        raise AssertionError("A rebuilt cross-partition SDK continuation is not durable.")

    monkeypatch.setattr(FakeQuery, "by_page", reject_rebuilt_pager)
    cursor, seen = None, []
    while True:
        page = repository.query("checkpoint", subject.scope_key, continuation=cursor, page_size=1)
        seen.extend(item["partition_key"] for item in page["items"])
        cursor = page["continuation"]
        if cursor is None:
            break
    assert set(seen) == {"one", "two", "three"}
    assert len(seen) == 3
    assert any("c.sort_key > @after" in query["query"] for query in repository.container.queries)
def test_events_are_idempotent_bounded_and_cannot_contain_evidence(persistence):
    repository, subject, *_ = persistence
    first = repository.append_event(subject, "held", "owner", {"finding_count": 2}, event_id="same-event")
    second = repository.append_event(subject, "held", "owner", {"finding_count": 2}, event_id="same-event")
    assert first == second
    with pytest.raises(ScreeningValidationError):
        repository.append_event(subject, "held", "owner", {"evidence": "private-canary"})
    with pytest.raises(ScreeningConflictError):
        repository.append_event(subject, "released", "owner", event_id="same-event")


def test_artifacts_are_private_hashed_immutable_and_revision_bound(persistence):
    _repository, subject, storage, service = persistence
    value = {"text": "private-canary", "units": ["last-page", "first-page"]}
    reference = storage.write_json(subject, "scan-private-name", "../../secret-filename.txt", value)
    assert storage.read_json(reference, subject) == value
    assert storage.write_json(subject, "scan-private-name", "../../secret-filename.txt", value) == reference
    container = service.get_container_client("content-screening")
    assert "private" not in reference["blob_name"]
    assert "secret-filename" not in reference["blob_name"]
    assert subject.scope_id not in reference["blob_name"]
    assert reference["sha256"] == hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    assert all(record["content_settings"].cache_control == "no-store" for record in container.blobs.values())
    with pytest.raises(ScreeningConflictError):
        storage.write_json(subject, "scan-private-name", "../../secret-filename.txt", {"text": "changed"})
    with pytest.raises(ScreeningConflictError):
        storage.read_json(reference, Subject("personal", "other", "doc", "2"))
    with pytest.raises(ScreeningConflictError):
        storage.read_json(reference, Subject("personal", "owner", "doc", "3"))


@pytest.mark.parametrize("tamper", [
    {"container": "user-documents"}, {"blob_name": "../user-documents/original"},
    {"blob_name": "https://example.invalid/private"}, {"size": -1}, {"artifact_key": "../outside"},
])
def test_untrusted_artifact_references_cannot_escape(persistence, tamper):
    _repository, subject, storage, service = persistence
    reference = storage.write_bytes(subject, "scan", "source", b"protected")
    reads = len(service.get_container_client("content-screening").reads)
    with pytest.raises((ScreeningConflictError, ScreeningValidationError)):
        storage.read_bytes({**reference, **tamper}, subject)
    assert len(service.get_container_client("content-screening").reads) == reads


def test_blob_etag_or_content_changes_fail_closed(persistence):
    _repository, subject, storage, service = persistence
    reference = storage.write_bytes(subject, "scan", "data", b"original")
    container = service.get_container_client("content-screening")
    part = next(path for path in container.blobs if "/part-" in path)
    container.blobs[part]["etag"] = "changed-etag"
    with pytest.raises(ScreeningConflictError):
        storage.read_bytes(reference, subject)
    container.blobs[part]["etag"] = '"blob-1"'
    container.blobs[part]["data"] = b"tampered"
    with pytest.raises(ScreeningConflictError):
        storage.read_bytes(reference, subject)


def test_segmented_artifacts_retry_partial_writes_without_overwriting(persistence, monkeypatch):
    _repository, subject, storage, service = persistence
    monkeypatch.setattr(storage_module, "PART_BYTES", 4)
    container = service.get_container_client("content-screening")
    container.fail_upload_name = "part-0001"
    with pytest.raises(FakeSdkError):
        storage.write_bytes(subject, "scan", "data", b"123456789")
    first_etag = next(iter(container.blobs.values()))["etag"]
    reference = storage.write_bytes(subject, "scan", "data", b"123456789")
    assert storage.read_bytes(reference, subject) == b"123456789"
    assert next(iter(container.blobs.values()))["etag"] == first_etag
    assert len(container.blobs) == 4
    assert all(read["length"] is None or read["length"] <= storage_module.MAX_MANIFEST_BYTES + 1 for read in container.reads)


def test_artifact_budgets_and_empty_sources(persistence, monkeypatch):
    _repository, subject, storage, _service = persistence
    monkeypatch.setattr(storage_module, "MAX_ARTIFACT_BYTES", 4)
    with pytest.raises(ScreeningValidationError):
        storage.write_bytes(subject, "scan", "large", b"12345")
    reference = storage.write_bytes(subject, "scan", "empty", b"")
    assert storage.read_bytes(reference, subject) == b""


def test_source_file_bytes_use_the_same_private_namespace_and_budget(persistence, monkeypatch):
    _repository, subject, storage, _service = persistence
    source = b"reviewer-only-original"
    fake_path = types.SimpleNamespace(
        is_file=lambda: True,
        stat=lambda: types.SimpleNamespace(st_size=len(source)),
        open=lambda _mode: io.BytesIO(source),
    )
    monkeypatch.setattr(storage_module, "Path", lambda _path: fake_path)
    reference = storage.write_source(subject, "scan", "server-generated-source", "..\\private-name.html")
    assert storage.read_bytes(reference, subject) == source
    assert "private-name" not in repr(reference)
    monkeypatch.setattr(storage_module, "MAX_ARTIFACT_BYTES", 1)
    with pytest.raises(ScreeningValidationError):
        storage.write_source(subject, "scan", "server-generated-source", "source.html")


def test_private_container_is_mandatory_without_any_fallback(persistence, monkeypatch):
    _repository, subject, _storage, service = persistence
    monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(CLIENTS={}))
    with pytest.raises(ScreeningConfigurationError):
        ScreeningStorage().write_json(subject, "scan", "content", [])
    for name in ("user-documents", "group-documents", "public-documents"):
        with pytest.raises(ScreeningConfigurationError):
            ScreeningStorage(service, name).validate_connection()
    container = service.get_container_client("content-screening")
    container.exists, container.public_access = True, "blob"
    with pytest.raises(ScreeningConfigurationError):
        ScreeningStorage(service).write_json(subject, "scan", "content", [])


def test_storage_rechecks_privacy_and_idempotent_content_hashes(persistence):
    _repository, subject, storage, service = persistence
    storage.write_bytes(subject, "scan", "original", b"original")
    container = service.get_container_client("content-screening")
    container.public_access = "container"
    with pytest.raises(ScreeningConfigurationError):
        storage.write_bytes(subject, "scan", "another", b"must-not-leak")
    container.public_access = None
    part = next(name for name in container.blobs if "part-" in name)
    container.blobs[part]["data"] = b"modified"
    with pytest.raises(ScreeningConflictError):
        storage.write_bytes(subject, "scan", "original", b"original")


def test_deletion_is_exact_revision_and_idempotent(persistence):
    _repository, subject, storage, service = persistence
    other = Subject("personal", "owner", "doc", "3")
    storage.write_bytes(subject, "scan", "source", b"one")
    second = storage.write_bytes(other, "scan", "source", b"two")
    storage.delete_revision(subject)
    storage.delete_revision(subject)
    assert storage.read_bytes(second, other) == b"two"
    assert all(subject.key in path for path in service.get_container_client("content-screening").deleted)


def test_copied_artifacts_require_explicit_hash_verified_rebinding(persistence):
    _repository, subject, source_storage, source_service = persistence
    reference = source_storage.write_json(subject, "scan", "units", {"content": "retained"})
    target_service = FakeBlobService()
    target_container = target_service.get_container_client("content-screening")
    target_container.exists = True
    target_container.blobs = copy.deepcopy(source_service.get_container_client("content-screening").blobs)
    for index, blob in enumerate(target_container.blobs.values()):
        blob["etag"] = f"copied-etag-{index}"
    target_storage = ScreeningStorage(target_service)
    with pytest.raises(ScreeningConflictError):
        target_storage.read_json(reference, subject)
    rebound = target_storage.rebind_transferred_reference(reference, subject)
    assert target_storage.read_json(rebound, subject) == {"content": "retained"}
    assert target_storage.rebind_transferred_reference(reference, subject) == rebound
    assert reference["blob_name"] != rebound["blob_name"]


def test_rebinding_never_accepts_modified_transferred_bytes(persistence):
    _repository, subject, storage, service = persistence
    reference = storage.write_bytes(subject, "scan", "source", b"original")
    container = service.get_container_client("content-screening")
    path = next(name for name in container.blobs if "/part-" in name)
    container.blobs[path].update({"etag": "new-account-etag", "data": b"tampered"})
    with pytest.raises(ScreeningConflictError):
        storage.rebind_transferred_reference(reference, subject)


def test_private_deletion_retries_after_partial_provider_failure(persistence, monkeypatch):
    _repository, subject, storage, service = persistence
    storage.write_bytes(subject, "scan", "original", b"private original")
    storage.write_bytes(subject, "scan", "units", b"private extracted text")
    other = Subject(subject.scope_type, subject.scope_id, subject.document_id, "other-revision")
    other_reference = storage.write_bytes(other, "scan", "original", b"other revision")
    original_delete = FakeBlob.delete_blob
    calls = []

    def fail_second_delete(blob, **kwargs):
        calls.append(blob.name)
        if len(calls) == 2:
            raise FakeSdkError(503)
        return original_delete(blob, **kwargs)

    monkeypatch.setattr(FakeBlob, "delete_blob", fail_second_delete)
    with pytest.raises(FakeSdkError):
        storage.delete_revision(subject)
    assert len(service.get_container_client("content-screening").deleted) == 1
    storage.delete_revision(subject)
    storage.delete_revision(subject)
    assert not any(subject.key in name for name in service.get_container_client("content-screening").blobs)
    assert storage.read_bytes(other_reference, other) == b"other revision"
