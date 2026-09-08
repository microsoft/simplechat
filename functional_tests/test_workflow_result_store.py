# test_workflow_result_store.py
"""
Functional tests for durable, scoped workflow task-result persistence.
Version: 0.261.106
Implemented in: 0.261.106

JSON-copying Cosmos and byte-copying Blob fakes exercise immutable writes,
backend selection, bounded range reads, identity/integrity checks, quota
enforcement, and cleanup beyond a history page. No deployed app is imported.
"""

import builtins
import hashlib
import importlib.util
import inspect
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError


STORE_PATH = Path(__file__).resolve().parents[1].joinpath(
    "application", "single_app", "functions_workflow_result_store.py",
)
SPEC = importlib.util.spec_from_file_location("isolated_workflow_result_store", STORE_PATH)
store_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store_module)


def json_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")


class FakeCosmosContainer:
    def __init__(self):
        self.records = {}
        self.reads = []
        self.creates = []
        self.deletes = []
        self.queries = []
        self.query_pages = []
        self.fail_create_at = None
        self.create_error = None
        self.read_error = None
        self.delete_error = None
        self.query_error = None

    def create_item(self, *, body):
        self.creates.append(body["id"])
        if self.fail_create_at == len(self.creates):
            raise self.create_error
        key = (body["run_id"], body["id"])
        if key in self.records:
            raise CosmosResourceExistsError(status_code=409, message="Fake provider conflict.")
        self.records[key] = json_copy(body)
        return json_copy(self.records[key])

    def read_item(self, *, item, partition_key):
        self.reads.append((partition_key, item))
        if self.read_error is not None:
            raise self.read_error
        if (partition_key, item) not in self.records:
            raise CosmosResourceNotFoundError(status_code=404, message="Fake provider item details.")
        return json_copy(self.records[(partition_key, item)])

    def delete_item(self, *, item, partition_key):
        if self.delete_error is not None:
            raise self.delete_error
        if (partition_key, item) not in self.records:
            raise CosmosResourceNotFoundError(status_code=404, message="Fake provider missing delete.")
        self.deletes.append((partition_key, item))
        del self.records[(partition_key, item)]

    def query_items(self, *, query, parameters, partition_key, max_item_count):
        self.queries.append({
            "query": query,
            "parameters": json_copy(parameters),
            "partition_key": partition_key,
            "max_item_count": max_item_count,
        })
        if self.query_error is not None:
            raise self.query_error
        values = {parameter["name"][1:]: parameter["value"] for parameter in parameters}
        keys = [
            key for key, row in self.records.items()
            if key[0] == partition_key
            and all(row.get(field) == values[field] for field in ("run_id", "workflow_id", "scope_type", "scope_id"))
            and row.get("type") == values["record_type"]
            and row.get("item_type") == values["record_type"]
        ]
        for start in range(0, len(keys), max_item_count):
            page = [json_copy(self.records[key]) for key in keys[start:start + max_item_count]]
            self.query_pages.append(len(page))
            yield from page


class FakeDownload:
    def __init__(self, data, owner, *, ranged):
        self.data = bytes(data)
        self.owner = owner
        self.ranged = ranged

    def readall(self):
        self.owner.readall_calls.append({"ranged": self.ranged, "size": len(self.data)})
        return bytes(self.data)

    def chunks(self):
        self.owner.stream_calls += 1
        for start in range(0, len(self.data), 64 * 1024):
            yield self.data[start:start + 64 * 1024]


class FakeBlob:
    def __init__(self, owner, container, name):
        self.owner = owner
        self.key = (container, name)

    def _row(self):
        if self.key not in self.owner.records:
            raise ResourceNotFoundError(message="Fake provider blob details.")
        return self.owner.records[self.key]

    def _check_etag(self, etag, match_condition):
        if etag is not None:
            if match_condition is not MatchConditions.IfNotModified or self._row()["etag"] != etag:
                raise ResourceModifiedError(message="Fake provider ETag mismatch.")

    def upload_blob(self, *, data, overwrite, metadata, content_settings):
        self.owner.uploads.append({"key": self.key, "overwrite": overwrite, "size": len(data)})
        if self.owner.upload_error is not None:
            raise self.owner.upload_error
        if overwrite:
            raise AssertionError("Result writes must never overwrite.")
        if self.key in self.owner.records:
            raise ResourceExistsError(message="Fake provider existing blob.")
        self.owner.etag_counter += 1
        self.owner.records[self.key] = {
            "data": bytes(data),
            "metadata": json_copy(metadata),
            "content_type": content_settings.content_type,
            "etag": f"etag-{self.owner.etag_counter}",
        }

    def get_blob_properties(self):
        row = self._row()
        self.owner.property_reads.append(self.key)
        return SimpleNamespace(
            name=self.key[1], size=len(row["data"]),
            metadata=json_copy(row["metadata"]), etag=row["etag"],
        )

    def download_blob(self, *, offset=None, length=None, etag=None, match_condition=None, validate_content=False):
        if self.owner.download_error is not None:
            raise self.owner.download_error
        self._check_etag(etag, match_condition)
        data = self._row()["data"]
        self.owner.downloads.append({
            "key": self.key, "offset": offset, "length": length,
            "etag": etag, "validate_content": validate_content,
        })
        if offset is not None:
            if length is None:
                raise AssertionError("A result page must use a bounded Blob range.")
            data = data[offset:offset + length]
        return FakeDownload(data, self.owner, ranged=offset is not None)

    def delete_blob(self, *, delete_snapshots, etag=None, match_condition=None):
        if self.owner.delete_error is not None:
            raise self.owner.delete_error
        self._check_etag(etag, match_condition)
        self._row()
        if delete_snapshots != "include":
            raise AssertionError("Private result snapshots should be cleaned with their blob.")
        self.owner.deletes.append(self.key)
        del self.owner.records[self.key]


class FakeBlobContainer:
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name

    def list_blobs(self, *, name_starts_with, include):
        self.owner.lists.append({"container": self.name, "prefix": name_starts_with, "include": include})
        if self.owner.list_error is not None:
            raise self.owner.list_error
        for container, name in list(self.owner.records):
            if container == self.name and name.startswith(name_starts_with):
                yield FakeBlob(self.owner, container, name).get_blob_properties()


class FakeBlobService:
    def __init__(self):
        self.records = {}
        self.uploads = []
        self.downloads = []
        self.property_reads = []
        self.readall_calls = []
        self.stream_calls = 0
        self.lists = []
        self.deletes = []
        self.etag_counter = 0
        self.upload_error = None
        self.download_error = None
        self.list_error = None
        self.delete_error = None

    def get_blob_client(self, *, container, blob):
        return FakeBlob(self, container, blob)

    def get_container_client(self, container):
        return FakeBlobContainer(self, container)


class WorkflowResultStoreTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {"id": "workflow/../#one", "user_id": "owner-one"}
        self.run_id = "run/../one"
        self.task_id = "task/../one"

    def make_store(self, *, blob=False, container=None, **kwargs):
        container = container if container is not None else FakeCosmosContainer()
        service = FakeBlobService() if blob else None
        store = store_module.WorkflowResultStore(
            container=container, blob_client=service, blob_container_name="personal-chat", **kwargs,
        )
        return store, container, service

    def save(self, store, result=None):
        return store.save(self.workflow, self.run_id, self.task_id, {"text": "result"} if result is None else result)

    def load(self, store, reference):
        return store.load(self.workflow, self.run_id, self.task_id, reference)

    def page(self, store, reference, **kwargs):
        return store.read_page(self.workflow, self.run_id, self.task_id, reference, **kwargs)

    def manifest_row(self, container):
        return next(row for row in container.records.values() if row["record_kind"] == "manifest")

    def chunk_row(self, container, index=0):
        return next(row for row in container.records.values() if row.get("chunk_index") == index)

    def test_json_fidelity_large_text_records_unicode_and_safe_references(self):
        original = {
            "unrecognized_contract": {"version": 987, "nullable": None, "boolean": True, "number": 1.125},
            "text": "🧪 中文 café \\ \"\n" * 24000,
            "records": [{"id": index, "values": [False, None, -index]} for index in range(2500)],
        }
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                result = json_copy(original)
                reference = self.save(store, result)
                result["text"] = "mutated after persistence"
                self.assertEqual(self.load(store, reference), original)
                self.assertEqual(set(reference), set(store_module.REFERENCE_FIELDS))
                self.assertEqual(reference["storage"], "blob" if blob else "cosmos")
                self.assertEqual(reference["size_bytes"], len(canonical_bytes(original)))
                self.assertEqual(reference["sha256"], hashlib.sha256(canonical_bytes(original)).hexdigest())
                safe_reference = json.dumps(reference)
                for forbidden in ("https:", "blob_path", "blob_url", "container", "owner-one", "workflow/"):
                    self.assertNotIn(forbidden, safe_reference)
                for row in container.records.values():
                    self.assertEqual(row["type"], "workflow_result_chunk")
                    self.assertEqual(row["item_type"], "workflow_result_chunk")
                    self.assertLess(len(json.dumps(row).encode("ascii")), 2 * 1024 * 1024)
                    if "payload" in row:
                        self.assertLessEqual(len(row["payload"]), store_module.MAX_COSMOS_CHUNK_BYTES)
                if blob:
                    self.assertEqual(len(container.records), 1)
                    blob_name = next(iter(service.records))[1]
                    self.assertTrue(blob_name.startswith("workflow-results/v1/personal/"))
                    self.assertNotIn("..", blob_name)
                    self.assertNotIn("owner-one", blob_name)
                    self.assertEqual(next(iter(service.records.values()))["content_type"], "application/json")

    def test_idempotent_writes_and_distinct_outputs_remain_immutable(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, chunk_size_bytes=16)
                first = self.save(store, {"z": "old", "a": [1, 2]})
                count = len(container.records)
                repeated = self.save(store, {"a": [1, 2], "z": "old"})
                self.assertEqual(first, repeated)
                self.assertEqual(len(container.records), count)
                second = self.save(store, {"z": "new", "a": [1, 2]})
                self.assertNotEqual(first["sha256"], second["sha256"])
                self.assertEqual(self.load(store, first)["z"], "old")
                self.assertEqual(self.load(store, second)["z"], "new")
                if blob:
                    self.assertEqual(len(service.records), 2)
                    self.assertTrue(all(upload["overwrite"] is False for upload in service.uploads))

    def test_existing_corrupt_content_is_not_overwritten_or_accepted(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                self.save(store, {"text": "original"})
                if blob:
                    row = next(iter(service.records.values()))
                    row["data"] = row["data"].replace(b"original", b"corrupt!")
                    damaged = bytes(row["data"])
                else:
                    row = self.chunk_row(container)
                    row["payload"] = row["payload"].replace("original", "corrupt!")
                    damaged = row["payload"]
                with self.assertRaises(store_module.WorkflowResultIntegrityError):
                    self.save(store, {"text": "original"})
                self.assertEqual(row["data"] if blob else row["payload"], damaged)

    def test_blob_failure_propagates_without_cosmos_fallback(self):
        store, container, service = self.make_store(blob=True)
        error = ServiceRequestError("Provider detail must not become a reference or page.")
        service.upload_error = error
        with self.assertRaises(ServiceRequestError) as raised:
            self.save(store)
        self.assertIs(raised.exception, error)
        self.assertEqual(container.creates, [])
        self.assertEqual(container.records, {})
        self.assertEqual(service.records, {})

    def test_interrupted_cosmos_write_has_no_manifest_and_can_resume(self):
        store, container, _ = self.make_store(chunk_size_bytes=16)
        error = ServiceRequestError("Fake Cosmos failure.")
        container.fail_create_at = 2
        container.create_error = error
        result = {"text": "r" * 200}
        with self.assertRaises(ServiceRequestError) as raised:
            self.save(store, result)
        self.assertIs(raised.exception, error)
        self.assertEqual(len(container.records), 1)
        self.assertFalse(any(row["record_kind"] == "manifest" for row in container.records.values()))
        incomplete = {field: next(iter(container.records.values()))[field] for field in store_module.REFERENCE_FIELDS}
        with self.assertRaises(CosmosResourceNotFoundError):
            self.load(store, incomplete)
        container.fail_create_at = None
        reference = self.save(store, result)
        self.assertEqual(self.load(store, reference), result)

    def test_blob_manifest_failure_is_recoverable_and_orphans_are_cleaned(self):
        for retry in (False, True):
            with self.subTest(retry=retry):
                store, container, service = self.make_store(blob=True)
                container.fail_create_at = 1
                container.create_error = ServiceRequestError("Fake manifest write failure.")
                with self.assertRaises(ServiceRequestError):
                    self.save(store)
                self.assertEqual(len(service.records), 1)
                self.assertEqual(container.records, {})
                if retry:
                    container.fail_create_at = None
                    reference = self.save(store)
                    self.assertEqual(self.load(store, reference), {"text": "result"})
                    self.assertEqual(len(service.records), 1)
                store.delete_run_results(self.workflow, self.run_id)
                self.assertEqual(service.records, {})
                self.assertEqual(container.records, {})

    def test_quota_measures_canonical_json_bytes_and_never_truncates(self):
        result = {"text": "😀" * 20}
        size = len(canonical_bytes(result))
        self.assertGreater(size, len(json.dumps(result, ensure_ascii=False)))
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, max_size_bytes=size - 1)
                with self.assertRaisesRegex(store_module.WorkflowResultTooLargeError, "byte size limit"):
                    self.save(store, result)
                self.assertEqual(container.creates, [])
                if service is not None:
                    self.assertEqual(service.uploads, [])
                store.max_size_bytes = size
                reference = self.save(store, result)
                self.assertEqual(reference["size_bytes"], size)
                self.assertEqual(self.load(store, reference), result)

    def test_blob_page_downloads_only_requested_range(self):
        store, container, service = self.make_store(blob=True)
        result = {"text": "😀" * 50000}
        expected = canonical_bytes(result)
        reference = self.save(store, result)
        container.reads.clear()
        page = self.page(store, reference, offset=35, limit=107)
        self.assertEqual(page["content"].encode("ascii"), expected[35:142])
        self.assertEqual(page["offset"], 35)
        self.assertEqual(page["next_offset"], 142)
        self.assertEqual(page["total_bytes"], len(expected))
        self.assertFalse(page["complete"])
        self.assertEqual(page["media_type"], "application/json")
        self.assertEqual(page["sha256"], reference["sha256"])
        self.assertFalse(page["integrity"]["full_sha256_verified"])
        self.assertFalse(page["integrity"]["chunk_sha256_verified"])
        self.assertEqual(page["integrity"]["page_sha256"], hashlib.sha256(expected[35:142]).hexdigest())
        self.assertEqual(len(container.reads), 1)
        self.assertEqual([(call["offset"], call["length"]) for call in service.downloads], [(35, 107)])
        self.assertTrue(service.downloads[0]["validate_content"])
        self.assertEqual(service.stream_calls, 0)
        self.assertEqual(service.readall_calls, [{"ranged": True, "size": 107}])

    def test_cosmos_page_reads_only_intersecting_chunks(self):
        store, container, _ = self.make_store(chunk_size_bytes=32)
        result = {"text": "data" * 10000}
        reference = self.save(store, result)
        container.reads.clear()
        page = self.page(store, reference, offset=60, limit=10)
        self.assertEqual(page["content"].encode("ascii"), canonical_bytes(result)[60:70])
        read_rows = [container.records[key] for key in container.reads]
        self.assertEqual([row["chunk_index"] for row in read_rows if row["record_kind"] == "chunk"], [1, 2])
        self.assertEqual(len(read_rows), 3)
        self.assertTrue(page["integrity"]["chunk_sha256_verified"])
        self.assertFalse(page["integrity"]["full_sha256_verified"])
        self.assertEqual(container.queries, [])

    def test_pages_reconstruct_exact_canonical_json_including_split_escapes(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, _ = self.make_store(blob=blob, chunk_size_bytes=13)
                result = {"text": "🧪\n中文\\\"" * 80, "records": [None, False, 1.5]}
                reference = self.save(store, result)
                offset = 0
                pages = []
                while offset is not None:
                    page = self.page(store, reference, offset=offset, limit=17)
                    pages.append(page["content"])
                    self.assertLessEqual(len(page["content"]), 17)
                    offset = page["next_offset"]
                payload = "".join(pages).encode("ascii")
                self.assertEqual(payload, canonical_bytes(result))
                self.assertEqual(json.loads(payload), result)
                self.assertTrue(page["complete"])
                self.assertFalse(page["integrity"]["full_sha256_verified"])

    def test_full_page_verifies_digest_and_eof_page_reads_no_payload(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                reference = self.save(store)
                self.assertTrue(self.page(store, reference)["integrity"]["full_sha256_verified"])
                container.reads.clear()
                if service is not None:
                    service.downloads.clear()
                eof = self.page(store, reference, offset=reference["size_bytes"], limit=1)
                self.assertEqual(eof["content"], "")
                self.assertIsNone(eof["next_offset"])
                self.assertTrue(eof["complete"])
                self.assertFalse(eof["integrity"]["full_sha256_verified"])
                self.assertFalse(eof["integrity"]["chunk_sha256_verified"])
                self.assertEqual(len(container.reads), 1)
                if service is not None:
                    self.assertEqual(service.downloads, [])

    def test_page_argument_types_bounds_and_hard_transport_maximum(self):
        store, container, _ = self.make_store()
        reference = self.save(store)
        invalid = [
            {"offset": True}, {"offset": -1}, {"offset": 1.0}, {"offset": "1"},
            {"limit": True}, {"limit": 0}, {"limit": -1}, {"limit": 1.0},
            {"limit": "10"}, {"limit": store_module.MAX_PAGE_BYTES + 1},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                container.reads.clear()
                with self.assertRaises(ValueError):
                    self.page(store, reference, **kwargs)
                self.assertEqual(container.reads, [])
        with self.assertRaises(ValueError):
            self.page(store, reference, offset=reference["size_bytes"] + 1)
        self.assertTrue(self.page(store, reference, limit=store_module.MAX_PAGE_BYTES)["complete"])

    def test_default_page_size_is_bounded(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, _ = self.make_store(blob=blob)
                reference = self.save(store, {"text": "x" * 100000})
                self.assertEqual(len(self.page(store, reference)["content"]), 65536)

    def test_wrong_scope_workflow_run_and_task_cannot_read_or_page(self):
        variants = [
            ({**self.workflow, "user_id": "another-user"}, self.run_id, self.task_id),
            ({**self.workflow, "group_id": "owner-one"}, self.run_id, self.task_id),
            ({**self.workflow, "id": "different-workflow"}, self.run_id, self.task_id),
            (self.workflow, "different-run", self.task_id),
            (self.workflow, self.run_id, "different-task"),
        ]
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, service = self.make_store(blob=blob)
                reference = self.save(store)
                for workflow, run_id, task_id in variants:
                    for method in (store.load, store.read_page):
                        with self.assertRaises(CosmosResourceNotFoundError):
                            method(workflow, run_id, task_id, reference)
                if service is not None:
                    self.assertEqual(service.downloads, [])

    def test_group_identity_is_not_the_current_actor(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, _ = self.make_store(blob=blob)
                workflow = {**self.workflow, "group_id": "group-one"}
                reference = store.save(workflow, self.run_id, self.task_id, {"text": "group result"})
                member_workflow = {**workflow, "user_id": "different-authorized-member"}
                self.assertEqual(store.load(member_workflow, self.run_id, self.task_id, reference)["text"], "group result")
                for invalid in ({**workflow, "group_id": "group-two"}, self.workflow):
                    with self.assertRaises(CosmosResourceNotFoundError):
                        store.load(invalid, self.run_id, self.task_id, reference)

    def test_stored_manifest_identity_is_checked_not_just_the_computed_key(self):
        for field, value in (
            ("scope_id", "other"), ("scope_type", "group"), ("workflow_id", "other"),
            ("run_id", "other"), ("task_id", "other"), ("schema_version", True),
            ("sha256", "0" * 64), ("size_bytes", 1), ("chunk_count", 900),
            ("type", "task_execution"), ("item_type", "task_execution"),
        ):
            with self.subTest(field=field):
                store, container, _ = self.make_store()
                reference = self.save(store)
                self.manifest_row(container)[field] = value
                for method in (self.load, self.page):
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        method(store, reference)

    def test_reference_paths_unknown_fields_and_tampered_fields_are_rejected(self):
        store, _, service = self.make_store(blob=True)
        reference = self.save(store)
        for update in (
            {"blob_path": "original-analyze/report.json"},
            {"url": "https://provider.invalid/private"},
            {"storage": "file"}, {"schema_version": True}, {"schema_version": 2},
            {"sha256": "../path"}, {"size_bytes": True}, {"size_bytes": -1},
            {"chunk_count": True}, {"chunk_count": 1},
        ):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    self.load(store, {**reference, **update})
        for update in ({"size_bytes": reference["size_bytes"] + 1}, {"sha256": "a" * 64}):
            with self.assertRaises((store_module.WorkflowResultIntegrityError, CosmosResourceNotFoundError)):
                self.load(store, {**reference, **update})
        self.assertEqual(service.downloads, [])

    def test_blob_metadata_is_verified_before_loading_or_paging(self):
        for key in ("scope_type", "scope_hash", "workflow_hash", "run_hash", "task_hash", "sha256", "size_bytes"):
            with self.subTest(key=key):
                store, _, service = self.make_store(blob=True)
                reference = self.save(store)
                next(iter(service.records.values()))["metadata"][key] = "wrong"
                for method in (self.load, self.page):
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        method(store, reference)
                self.assertEqual(service.downloads, [])

    def test_missing_blob_and_provider_read_failures_propagate(self):
        store, container, service = self.make_store(blob=True)
        reference = self.save(store)
        error = ServiceRequestError("Fake provider read failure.")
        service.download_error = error
        with self.assertRaises(ServiceRequestError) as raised:
            self.load(store, reference)
        self.assertIs(raised.exception, error)
        service.download_error = None
        service.records.clear()
        for method in (self.load, self.page):
            with self.assertRaises(ResourceNotFoundError):
                method(store, reference)
        container.read_error = error
        with self.assertRaises(ServiceRequestError) as raised:
            self.load(store, reference)
        self.assertIs(raised.exception, error)

    def test_blob_reads_are_bound_to_the_verified_metadata_etag(self):
        store, _, _ = self.make_store(blob=True)
        reference = self.save(store)
        original_properties = FakeBlob.get_blob_properties

        def change_after_properties(blob):
            properties = original_properties(blob)
            blob._row()["etag"] += "-changed"
            return properties

        with patch.object(FakeBlob, "get_blob_properties", change_after_properties):
            for method in (self.load, self.page):
                with self.assertRaises(ResourceModifiedError):
                    method(store, reference)

    def test_blob_corruption_fails_full_load_and_does_not_claim_partial_integrity(self):
        store, _, service = self.make_store(blob=True)
        reference = self.save(store, {"text": "original"})
        row = next(iter(service.records.values()))
        row["data"] = row["data"].replace(b"original", b"corrupt!")
        for method in (self.load, self.page):
            with self.assertRaises(store_module.WorkflowResultIntegrityError):
                method(store, reference)
        partial = self.page(store, reference, offset=9, limit=3)
        self.assertFalse(partial["integrity"]["full_sha256_verified"])
        self.assertFalse(partial["integrity"]["chunk_sha256_verified"])
        row["data"] += b"x"
        with self.assertRaises(store_module.WorkflowResultIntegrityError):
            self.page(store, reference, offset=0, limit=1)

    def test_missing_chunks_fail_load_and_intersecting_page(self):
        store, container, _ = self.make_store(chunk_size_bytes=16)
        reference = self.save(store, {"text": "x" * 150})
        row = self.chunk_row(container, 2)
        del container.records[(self.run_id, row["id"])]
        with self.assertRaises(CosmosResourceNotFoundError):
            self.load(store, reference)
        with self.assertRaises(CosmosResourceNotFoundError):
            self.page(store, reference, offset=32, limit=1)
        self.assertEqual(len(self.page(store, reference, offset=0, limit=1)["content"]), 1)

    def test_corrupt_chunks_and_chunk_identity_fail_explicitly(self):
        for field, value in (
            ("payload", "bad"), ("payload", "é" * 16), ("payload_size_bytes", 1),
            ("payload_sha256", "0" * 64), ("chunk_index", True), ("task_id", "different-task"),
            ("scope_id", "different-user"), ("sha256", "a" * 64),
        ):
            with self.subTest(field=field):
                store, container, _ = self.make_store(chunk_size_bytes=16)
                reference = self.save(store, {"text": "x" * 100})
                self.chunk_row(container)[field] = value
                for method in (self.load, self.page):
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        method(store, reference)

    def test_full_digest_catches_chunk_content_even_when_local_hash_matches(self):
        store, container, _ = self.make_store()
        reference = self.save(store, {"text": "original"})
        row = self.chunk_row(container)
        row["payload"] = row["payload"].replace("original", "corrupt!")
        row["payload_sha256"] = hashlib.sha256(row["payload"].encode("ascii")).hexdigest()
        for method in (self.load, self.page):
            with self.assertRaises(store_module.WorkflowResultIntegrityError):
                method(store, reference)

    def test_read_backend_is_persisted_not_selected_from_current_configuration(self):
        store, container, _ = self.make_store()
        reference = self.save(store)
        with_blob = store_module.WorkflowResultStore(container, FakeBlobService(), "personal-chat", max_size_bytes=1)
        self.assertEqual(self.load(with_blob, reference), {"text": "result"})
        with_blob.max_size_bytes = 1024
        blob_reference = self.save(with_blob, {})
        without_blob = store_module.WorkflowResultStore(container)
        with self.assertRaises(store_module.WorkflowResultStorageUnavailableError):
            self.load(without_blob, blob_reference)

    def test_cleanup_streams_more_than_1000_chunks_and_preserves_other_scope_data(self):
        store, container, _ = self.make_store(chunk_size_bytes=16)
        reference = self.save(store, {"text": "x" * 17000})
        self.assertGreater(reference["chunk_count"], 1000)
        targets = set(container.records)
        for workflow, run_id in (
            ({**self.workflow, "user_id": "other-user"}, self.run_id),
            ({**self.workflow, "id": "other-workflow"}, self.run_id),
            ({**self.workflow, "group_id": "owner-one"}, self.run_id),
            (self.workflow, "other-run"),
        ):
            store.save(workflow, run_id, self.task_id, {"text": "keep"})
        container.create_item(body={
            "id": "user-visible-task", "run_id": self.run_id, "workflow_id": self.workflow["id"],
            "scope_type": "personal", "scope_id": self.workflow["user_id"],
            "type": "task_execution", "item_type": "task_execution",
        })
        expected_remaining = {key: json_copy(row) for key, row in container.records.items() if key not in targets}
        store.delete_run_results(self.workflow, self.run_id)
        self.assertEqual(container.records, expected_remaining)
        self.assertEqual(set(container.deletes), targets)
        self.assertGreater(len(container.query_pages), 10)
        self.assertTrue(all(count <= 100 for count in container.query_pages))
        self.assertNotIn("TOP", container.queries[0]["query"])
        self.assertNotIn("SELECT *", container.queries[0]["query"])
        self.assertNotIn("c.payload", container.queries[0]["query"])
        self.assertEqual(container.queries[0]["partition_key"], self.run_id)
        store.delete_run_results(self.workflow, self.run_id)
        self.assertEqual(container.records, expected_remaining)

    def test_cleanup_blob_prefix_is_scoped_and_cleans_orphaned_payloads(self):
        store, container, service = self.make_store(blob=True)
        self.save(store)
        store.save(self.workflow, self.run_id, "another-task", {"text": "orphan"})
        orphan_manifest = next(row for row in container.records.values() if row["task_id"] == "another-task")
        del container.records[(self.run_id, orphan_manifest["id"])]
        targets = set(service.records)
        for workflow, run_id in (
            ({**self.workflow, "user_id": "other-user"}, self.run_id),
            ({**self.workflow, "id": "other-workflow"}, self.run_id),
            ({**self.workflow, "group_id": "owner-one"}, self.run_id),
            (self.workflow, "other-run"),
        ):
            store.save(workflow, run_id, self.task_id, {"text": "keep"})
        for key in (
            ("personal-chat", "analyze/original-document.pdf"),
            ("user-documents", "published-report.json"),
            ("personal-chat", "workflow-results/not-this-run.json"),
        ):
            service.records[key] = {"data": b"keep", "metadata": {}, "etag": "keep"}
        keep = {key: row for key, row in service.records.items() if key not in targets}
        store.delete_run_results(self.workflow, self.run_id)
        self.assertEqual(service.records, keep)
        self.assertEqual(set(service.deletes), targets)
        self.assertEqual(len(service.lists), 1)
        self.assertTrue(service.lists[0]["prefix"].startswith("workflow-results/v1/personal/"))
        self.assertTrue(service.lists[0]["prefix"].endswith("/"))
        self.assertTrue(all(key[1].startswith(service.lists[0]["prefix"]) for key in service.deletes))
        self.assertTrue(all(row["scope_id"] != "owner-one" or row["workflow_id"] != self.workflow["id"]
                            or row["run_id"] != self.run_id or row["scope_type"] != "personal"
                            for row in container.records.values()))

    def test_cleanup_group_does_not_delete_another_group(self):
        store, container, service = self.make_store(blob=True)
        workflow = {**self.workflow, "group_id": "first-group"}
        other = {**workflow, "group_id": "second-group"}
        first = store.save(workflow, self.run_id, self.task_id, {"text": "first"})
        second = store.save(other, self.run_id, self.task_id, {"text": "second"})
        store.delete_run_results({**workflow, "user_id": "another-member"}, self.run_id)
        with self.assertRaises(CosmosResourceNotFoundError):
            store.load(workflow, self.run_id, self.task_id, first)
        self.assertEqual(store.load(other, self.run_id, self.task_id, second), {"text": "second"})
        self.assertEqual(len(container.records), 1)
        self.assertEqual(len(service.records), 1)

    def test_cleanup_missing_blob_configuration_fails_without_discarding_manifest(self):
        store, container, _ = self.make_store(blob=True)
        self.save(store)
        without_blob = store_module.WorkflowResultStore(container)
        with self.assertRaises(store_module.WorkflowResultStorageUnavailableError):
            without_blob.delete_run_results(self.workflow, self.run_id)
        self.assertEqual(len(container.records), 1)
        self.assertEqual(container.deletes, [])

    def test_cleanup_errors_propagate_and_preserve_history_boundary(self):
        store, container, service = self.make_store(blob=True)
        self.save(store)
        error = ServiceRequestError("Fake provider cleanup error.")
        for field in ("list_error", "delete_error"):
            with self.subTest(field=field):
                setattr(service, field, error)
                with self.assertRaises(ServiceRequestError) as raised:
                    store.delete_run_results(self.workflow, self.run_id)
                self.assertIs(raised.exception, error)
                self.assertEqual(container.deletes, [])
                setattr(service, field, None)
        store, container, _ = self.make_store()
        self.save(store)
        for field in ("query_error", "delete_error"):
            with self.subTest(field=field):
                setattr(container, field, error)
                with self.assertRaises(ServiceRequestError) as raised:
                    store.delete_run_results(self.workflow, self.run_id)
                self.assertIs(raised.exception, error)
                setattr(container, field, None)

    def test_cleanup_refuses_unrecognized_blob_or_wrong_stored_scope(self):
        for corrupt_metadata in (False, True):
            with self.subTest(corrupt_metadata=corrupt_metadata):
                store, container, service = self.make_store(blob=True)
                self.save(store)
                key = next(iter(service.records))
                if corrupt_metadata:
                    service.records[key]["metadata"]["scope_hash"] = "0" * 64
                else:
                    row = service.records.pop(key)
                    service.records[(key[0], key[1].rsplit("/", 2)[0] + "/original-analyze.pdf")] = row
                with self.assertRaises(store_module.WorkflowResultIntegrityError):
                    store.delete_run_results(self.workflow, self.run_id)
                self.assertEqual(service.deletes, [])
                self.assertEqual(container.deletes, [])

    def test_cleanup_removes_incomplete_cosmos_chunks(self):
        store, container, _ = self.make_store(chunk_size_bytes=16)
        container.fail_create_at = 3
        container.create_error = ServiceRequestError("Interrupted.")
        with self.assertRaises(ServiceRequestError):
            self.save(store, {"text": "x" * 100})
        self.assertEqual(len(container.records), 2)
        store.delete_run_results(self.workflow, self.run_id)
        self.assertEqual(container.records, {})

    def test_invalid_inputs_and_chunk_sizes_fail_before_writes(self):
        for kwargs in (
            {"chunk_size_bytes": True}, {"chunk_size_bytes": 0},
            {"chunk_size_bytes": store_module.MAX_COSMOS_CHUNK_BYTES + 1},
            {"max_size_bytes": True}, {"max_size_bytes": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.make_store(**kwargs)
        store, container, _ = self.make_store()
        for result in ([], None, {"number": float("nan")}, {"not_json": object()}):
            with self.subTest(result_type=type(result).__name__):
                with self.assertRaises((ValueError, TypeError)):
                    store.save(self.workflow, self.run_id, self.task_id, result)
        for workflow in ({}, {**self.workflow, "group_id": False}, {**self.workflow, "user_id": ""}):
            with self.assertRaises(ValueError):
                store.save(workflow, self.run_id, self.task_id, {})
        self.assertEqual(container.creates, [])

    def test_module_import_does_not_import_config_or_workflow_stores(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in {"config", "functions_settings", "functions_personal_workflows", "functions_group_workflows"}:
                raise AssertionError(f"Unexpected app initialization through {name}.")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            spec = importlib.util.spec_from_file_location("import_safe_workflow_result_store", STORE_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.WorkflowResultStore))

    def test_configured_public_api_selects_personal_group_and_optional_backends(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                personal = FakeCosmosContainer()
                group = FakeCosmosContainer()
                settings = FakeCosmosContainer()
                settings.create_item(body={
                    "id": "app_settings", "run_id": "app_settings",
                    "max_generated_chat_artifact_size_mb": 1,
                })
                service = FakeBlobService() if blob else None
                config = SimpleNamespace(
                    CLIENTS={"storage_account_office_docs_client": service} if blob else {},
                    cosmos_personal_workflow_run_items_container=personal,
                    cosmos_group_workflow_run_items_container=group,
                    cosmos_settings_container=settings,
                    storage_account_personal_chat_container_name="configured-personal-chat",
                )
                with patch.dict(sys.modules, {"config": config}):
                    for workflow in (self.workflow, {**self.workflow, "group_id": "group-one"}):
                        reference = store_module.save_workflow_task_result(
                            workflow, self.run_id, self.task_id, {"text": "configured"},
                        )
                        self.assertEqual(reference["storage"], "blob" if blob else "cosmos")
                        self.assertEqual(
                            store_module.load_workflow_task_result(workflow, self.run_id, self.task_id, reference),
                            {"text": "configured"},
                        )
                        page = store_module.read_workflow_task_result_page(
                            workflow, self.run_id, self.task_id, reference, offset=1, limit=2,
                        )
                        self.assertEqual(page["content"], canonical_bytes({"text": "configured"})[1:3].decode("ascii"))
                        store_module.delete_workflow_run_results(workflow, self.run_id)
                    self.assertEqual(personal.records, {})
                    self.assertEqual(group.records, {})
                    self.assertEqual(settings.reads, [("app_settings", "app_settings")] * 2)
                    if blob:
                        self.assertTrue(all(upload["key"][0] == "configured-personal-chat" for upload in service.uploads))

    def test_configured_quota_default_and_explicit_values(self):
        config = SimpleNamespace(
            CLIENTS={},
            cosmos_personal_workflow_run_items_container=FakeCosmosContainer(),
            cosmos_group_workflow_run_items_container=FakeCosmosContainer(),
            storage_account_personal_chat_container_name="personal-chat",
        )
        with patch.dict(sys.modules, {"config": config}):
            self.assertEqual(
                store_module._configured_store(self.workflow, settings={}).max_size_bytes, 500 * 1024 * 1024,
            )
            self.assertEqual(
                store_module._configured_store(
                    self.workflow, settings={"max_generated_chat_artifact_size_mb": "1"},
                ).max_size_bytes,
                1024 * 1024,
            )
            with self.assertRaises(store_module.WorkflowResultTooLargeError):
                store_module.save_workflow_task_result(
                    self.workflow, self.run_id, self.task_id, {"text": "x" * (1024 * 1024)},
                    settings={"max_generated_chat_artifact_size_mb": 1},
                )
            for value in (True, None, 0, -1, "not-a-number", 1.5):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError):
                        store_module.save_workflow_task_result(
                            self.workflow, self.run_id, self.task_id, {},
                            settings={"max_generated_chat_artifact_size_mb": value},
                        )
            self.assertEqual(config.cosmos_personal_workflow_run_items_container.creates, [])

    def test_public_api_signatures_are_stable(self):
        expected = {
            "save_workflow_task_result": ["workflow", "run_id", "task_id", "result", "settings"],
            "load_workflow_task_result": ["workflow", "run_id", "task_id", "reference"],
            "read_workflow_task_result_page": ["workflow", "run_id", "task_id", "reference", "offset", "limit"],
            "delete_workflow_run_results": ["workflow", "run_id"],
        }
        for name, parameters in expected.items():
            signature = inspect.signature(getattr(store_module, name))
            self.assertEqual(list(signature.parameters), parameters)
        signature = inspect.signature(store_module.read_workflow_task_result_page)
        self.assertEqual(signature.parameters["offset"].default, 0)
        self.assertEqual(signature.parameters["limit"].default, 65536)
        self.assertEqual(signature.parameters["offset"].kind, inspect.Parameter.KEYWORD_ONLY)


if __name__ == "__main__":
    unittest.main()
