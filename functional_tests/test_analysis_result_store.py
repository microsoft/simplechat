# test_analysis_result_store.py
"""
Functional tests for chat/orchestration reuse of the shared immutable result store.
Version: 0.261.107
Implemented in: 0.261.107

The existing SDK doubles exercise real owner/conversation/assistant-message or
orchestration-run/step bindings, shared JSON/chunk/digest semantics, and private
cleanup without a workflow row, UI payload, or application startup dependency.
Current source authorization and execution/deletion fencing belong to callers.
"""

import hashlib
import inspect
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError, ServiceRequestError
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from test_workflow_result_store import (
    FakeBlob,
    FakeBlobService,
    FakeCosmosContainer,
    canonical_bytes,
    json_copy,
    store_module,
)


def identifier_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_store(*, blob=False, **kwargs):
    container = FakeCosmosContainer()
    service = FakeBlobService() if blob else None
    store = store_module.WorkflowResultStore(container, service, "personal-chat", **kwargs)
    return store, container, service


class ChatAnalysisResultStoreTests(unittest.TestCase):
    make_store = staticmethod(make_store)

    def setUp(self):
        self.user_id = "original-owner"
        self.conversation_id = "conversation/../#one"
        self.message_id = "assistant-message/../#one"

    def save(self, store, result=None):
        return store.save_chat(
            self.user_id, self.conversation_id, self.message_id,
            {"text": "saved final"} if result is None else result,
        )

    def load(self, store, reference):
        return store.load_chat(self.user_id, self.conversation_id, self.message_id, reference)

    def page(self, store, reference, **kwargs):
        return store.read_chat_page(
            self.user_id, self.conversation_id, self.message_id, reference, **kwargs,
        )

    def delete(self, store, *, conversation=False):
        return store.delete_chat_results(
            self.user_id, self.conversation_id, None if conversation else self.message_id,
        )

    def test_chat_round_trip_has_real_identity_and_exact_path_free_reference(self):
        result = {
            "unknown_contract": {"version": 987, "nullable": None, "boolean": True},
            "text": "🧪 中文 café \\ \"\n" * 10000,
            "records": [{"id": index, "values": [None, False, 1.25]} for index in range(1000)],
        }
        identity = {
            "scope_type": "chat", "scope_id": self.conversation_id,
            "user_id": self.user_id, "conversation_id": self.conversation_id,
            "run_id": self.message_id, "message_id": self.message_id,
        }
        identity_digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=True).encode("ascii"),
        ).hexdigest()
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                supplied = json_copy(result)
                reference = self.save(store, supplied)
                supplied["text"] = "mutated after persistence"
                reloaded = store_module.WorkflowResultStore(container, service, "personal-chat")
                self.assertEqual(self.load(reloaded, reference), result)
                self.assertEqual(set(reference), {"storage", "schema_version", "sha256", "size_bytes", "chunk_count"})
                self.assertEqual(reference["schema_version"], 1)
                self.assertEqual(reference["sha256"], hashlib.sha256(canonical_bytes(result)).hexdigest())
                self.assertEqual(reference["size_bytes"], len(canonical_bytes(result)))
                self.assertEqual(reference["storage"], "blob" if blob else "cosmos")
                self.assertEqual(reference["chunk_count"], 0 if blob else (
                    len(canonical_bytes(result)) + store.chunk_size_bytes - 1
                ) // store.chunk_size_bytes)
                for forbidden in (self.user_id, self.conversation_id, self.message_id, "url", "path", "container"):
                    self.assertNotIn(forbidden, json.dumps(reference))
                for (partition, record_id), row in container.records.items():
                    self.assertEqual(partition, self.message_id)
                    for key, value in identity.items():
                        self.assertEqual(row[key], value)
                    self.assertEqual(row["type"], "chat_analysis_result_chunk")
                    self.assertEqual(row["item_type"], "chat_analysis_result_chunk")
                    self.assertNotIn("workflow_id", row)
                    self.assertNotIn("task_id", row)
                    self.assertTrue(record_id.startswith(
                        f"chat-analysis-result:v1:{identity_digest}:{reference['storage']}:{reference['sha256']}:",
                    ))
                    self.assertLess(len(json.dumps(row).encode("ascii")), 2 * 1024 * 1024)
                if blob:
                    self.assertEqual(len(container.records), 1)
                    name = (
                        f"chat-analysis-results/v1/chat/{identifier_hash(self.user_id)}/"
                        f"{identifier_hash(self.conversation_id)}/{identifier_hash(self.message_id)}/"
                        f"{reference['sha256']}.json"
                    )
                    row = service.records[("personal-chat", name)]
                    self.assertEqual(row["content_type"], "application/json")
                    self.assertEqual(row["metadata"], {
                        "schema_version": "1", "scope_type": "chat",
                        "scope_hash": identifier_hash(self.conversation_id),
                        "user_hash": identifier_hash(self.user_id),
                        "conversation_hash": identifier_hash(self.conversation_id),
                        "run_hash": identifier_hash(self.message_id),
                        "message_hash": identifier_hash(self.message_id),
                        "sha256": reference["sha256"], "size_bytes": str(reference["size_bytes"]),
                        "media_type": "application/json",
                    })

    def test_replay_sections_and_revisions_reuse_immutable_shared_io(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, chunk_size_bytes=16)
                original = {"text": "first", "records": [1, 2]}
                first = self.save(store, original)
                snapshot = json_copy(list(container.records.values()))
                replay = self.save(store, {"records": [1, 2], "text": "first"})
                self.assertEqual(replay, first)
                self.assertEqual(list(container.records.values()), snapshot)
                second = self.save(store, {"text": "revised", "records": [1, 2]})
                diagnostics = self.save(store, {"diagnostics": ["not authoritative"]})
                self.assertEqual(len({ref["sha256"] for ref in (first, second, diagnostics)}), 3)
                self.assertEqual(self.load(store, first), original)
                self.assertEqual(self.load(store, second)["text"], "revised")
                self.assertEqual(self.load(store, diagnostics), {"diagnostics": ["not authoritative"]})
                if blob:
                    self.assertEqual(len(service.records), 3)
                    self.assertTrue(all(upload["overwrite"] is False for upload in service.uploads))

    def test_foreign_owner_conversation_message_and_workflow_bindings_cannot_read(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, service = self.make_store(blob=blob)
                reference = self.save(store)
                variants = [
                    ("another-owner", self.conversation_id, self.message_id),
                    (self.user_id, "another-conversation", self.message_id),
                    (self.user_id, self.conversation_id, "another-message"),
                    (self.conversation_id, self.user_id, self.message_id),
                    (self.user_id, self.message_id, self.conversation_id),
                ]
                for identity in variants:
                    for method in (store.load_chat, store.read_chat_page):
                        with self.assertRaises(CosmosResourceNotFoundError):
                            method(*identity, reference)
                workflow = {"id": self.conversation_id, "user_id": self.user_id}
                for method in (store.load, store.read_page):
                    with self.assertRaises(CosmosResourceNotFoundError):
                        method(workflow, self.message_id, self.message_id, reference)
                if blob:
                    self.assertEqual(service.downloads, [])

    def test_workflow_and_chat_with_identical_ids_and_payloads_do_not_collide(self):
        workflow = {"id": self.conversation_id, "user_id": self.user_id}
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, _ = self.make_store(blob=blob)
                result = {"text": "identical bytes, different authorized context"}
                chat_reference = self.save(store, result)
                with self.assertRaises(CosmosResourceNotFoundError):
                    store.load(workflow, self.message_id, self.message_id, chat_reference)
                workflow_reference = store.save(workflow, self.message_id, self.message_id, result)
                self.assertEqual(workflow_reference, chat_reference)
                store.delete_run_results(workflow, self.message_id)
                self.assertEqual(self.load(store, chat_reference), result)
                store.save(workflow, self.message_id, self.message_id, result)
                self.delete(store, conversation=True)
                self.assertEqual(store.load(workflow, self.message_id, self.message_id, workflow_reference), result)

    def test_each_chat_manifest_and_chunk_identity_field_is_checked(self):
        fields = {
            "user_id": "foreign-owner", "conversation_id": "foreign-conversation",
            "message_id": "foreign-message", "run_id": "foreign-run",
            "scope_id": "foreign-scope", "scope_type": "personal",
            "type": "workflow_result_chunk", "item_type": "workflow_result_chunk",
        }
        for blob, kind in ((False, "manifest"), (False, "chunk"), (True, "manifest")):
            for field, value in fields.items():
                with self.subTest(blob=blob, kind=kind, field=field):
                    store, container, service = self.make_store(blob=blob)
                    reference = self.save(store)
                    row = next(row for row in container.records.values() if row["record_kind"] == kind)
                    row[field] = value
                    for method in (self.load, self.page):
                        with self.assertRaises(store_module.WorkflowResultIntegrityError):
                            method(store, reference)
                    if blob:
                        self.assertEqual(service.downloads, [])

    def test_chat_blob_metadata_denies_read_page_and_replay_before_downloading(self):
        for field in (
            "schema_version", "scope_type", "scope_hash", "user_hash", "conversation_hash",
            "run_hash", "message_hash", "sha256", "size_bytes", "media_type",
        ):
            with self.subTest(field=field):
                store, _, service = self.make_store(blob=True)
                reference = self.save(store)
                next(iter(service.records.values()))["metadata"][field] = "foreign"
                for method in (self.load, self.page):
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        method(store, reference)
                with self.assertRaises(store_module.WorkflowResultIntegrityError):
                    self.save(store)
                self.assertEqual(service.downloads, [])

    def test_chat_reference_never_accepts_caller_paths_or_identity_fields(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                reference = self.save(store)
                container.reads.clear()
                for update in (
                    {"blob_path": "published-report.json"}, {"url": "https://provider.invalid/private"},
                    {"user_id": self.user_id}, {"conversation_id": self.conversation_id},
                    {"message_id": self.message_id}, {"storage": "file"}, {"schema_version": True},
                    {"sha256": "../path"}, {"size_bytes": True}, {"chunk_count": True},
                ):
                    for method in (self.load, self.page):
                        with self.assertRaises(ValueError):
                            method(store, {**reference, **update})
                with self.assertRaises(ValueError):
                    self.load(store, {key: value for key, value in reference.items() if key != "sha256"})
                self.assertEqual(container.reads, [])
                if blob:
                    self.assertEqual(service.downloads, [])

    def test_invalid_chat_identities_fail_before_io_and_lazy_configuration(self):
        store, container, service = self.make_store(blob=True)
        reference = {"storage": "blob", "schema_version": 1, "sha256": "a" * 64, "size_bytes": 2, "chunk_count": 0}
        methods = (
            (store.save_chat, ({},)), (store.load_chat, (reference,)),
            (store.read_chat_page, (reference,)),
            (store_module.save_chat_analysis_result, ({},)),
            (store_module.load_chat_analysis_result, (reference,)),
            (store_module.read_chat_analysis_result_page, (reference,)),
        )
        with patch.object(store_module, "_configured_result_store", side_effect=AssertionError("Unexpected config access.")):
            for index in range(3):
                for invalid in (None, "", True, 42, {}, "x" * 1025, "😀" * 257):
                    identity = [self.user_id, self.conversation_id, self.message_id]
                    identity[index] = invalid
                    with self.subTest(index=index, invalid_type=type(invalid).__name__):
                        for method, arguments in methods:
                            with self.assertRaises(ValueError):
                                method(*identity, *arguments)
                        if not (index == 2 and invalid is None):
                            for method in (store.delete_chat_results, store_module.delete_chat_analysis_results):
                                with self.assertRaises(ValueError):
                                    method(*identity)
        self.assertEqual(container.reads, [])
        self.assertEqual(container.creates, [])
        self.assertEqual(container.queries, [])
        self.assertEqual(service.uploads, [])
        self.assertEqual(service.lists, [])

    def test_chat_pages_are_byte_transport_with_bounded_ranges_and_split_escapes(self):
        result = {"text": "😀中文\\\"" * 30, "records": [None, False, 1.25]}
        expected = canonical_bytes(result)
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, chunk_size_bytes=32)
                reference = self.save(store, result)
                container.reads.clear()
                page = self.page(store, reference, offset=29, limit=10)
                self.assertEqual(page["content"].encode("ascii"), expected[29:39])
                self.assertFalse(page["integrity"]["full_sha256_verified"])
                if blob:
                    self.assertEqual([(call["offset"], call["length"]) for call in service.downloads], [(29, 10)])
                    self.assertEqual(service.stream_calls, 0)
                else:
                    chunks = [container.records[key]["chunk_index"] for key in container.reads
                              if container.records[key]["record_kind"] == "chunk"]
                    self.assertEqual(chunks, [0, 1])
                    self.assertTrue(page["integrity"]["chunk_sha256_verified"])
                offset, contents = 0, []
                while offset is not None:
                    page = self.page(store, reference, offset=offset, limit=13)
                    contents.append(page["content"])
                    self.assertLessEqual(len(page["content"]), 13)
                    offset = page["next_offset"]
                self.assertEqual("".join(contents).encode("ascii"), expected)
                self.assertTrue(page["complete"])
                self.assertFalse(page["integrity"]["full_sha256_verified"])
                self.assertTrue(self.page(store, reference)["integrity"]["full_sha256_verified"])
                self.assertEqual(self.page(store, reference, offset=len(expected))["content"], "")
                for arguments in ({"offset": True}, {"offset": -1}, {"limit": True}, {"limit": 0},
                                  {"limit": store_module.MAX_PAGE_BYTES + 1}):
                    container.reads.clear()
                    with self.assertRaises(ValueError):
                        self.page(store, reference, **arguments)
                    self.assertEqual(container.reads, [])

    def test_corrupt_payloads_fail_full_digest_and_immutable_replay(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                reference = self.save(store, {"text": "original"})
                if blob:
                    row = next(iter(service.records.values()))
                    row["data"] = row["data"].replace(b"original", b"corrupt!")
                else:
                    row = next(row for row in container.records.values() if row["record_kind"] == "chunk")
                    row["payload"] = row["payload"].replace("original", "corrupt!")
                    row["payload_sha256"] = hashlib.sha256(row["payload"].encode("ascii")).hexdigest()
                for method in (self.load, self.page):
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        method(store, reference)
                with self.assertRaises(store_module.WorkflowResultIntegrityError):
                    self.save(store, {"text": "original"})
                self.assertFalse(self.page(store, reference, offset=9, limit=3)["integrity"]["full_sha256_verified"])

    def test_interrupted_writes_remain_unreadable_then_resume_or_sweep(self):
        result = {"text": "x" * 200}
        for blob in (False, True):
            for retry in (False, True):
                for conversation in (False, True):
                    with self.subTest(blob=blob, retry=retry, conversation=conversation):
                        store, container, service = self.make_store(blob=blob, chunk_size_bytes=16)
                        container.fail_create_at = 1 if blob else 2
                        error = ServiceRequestError("Interrupted provider write.")
                        container.create_error = error
                        with self.assertRaises(ServiceRequestError) as raised:
                            self.save(store, result)
                        self.assertIs(raised.exception, error)
                        self.assertFalse(any(row["record_kind"] == "manifest" for row in container.records.values()))
                        reference = {
                            "storage": "blob" if blob else "cosmos", "schema_version": 1,
                            "sha256": hashlib.sha256(canonical_bytes(result)).hexdigest(),
                            "size_bytes": len(canonical_bytes(result)),
                            "chunk_count": 0 if blob else (len(canonical_bytes(result)) + 15) // 16,
                        }
                        for method in (self.load, self.page):
                            with self.assertRaises(CosmosResourceNotFoundError):
                                method(store, reference)
                        if retry:
                            container.fail_create_at = None
                            self.assertEqual(self.save(store, result), reference)
                            self.assertEqual(self.load(store, reference), result)
                        self.delete(store, conversation=conversation)
                        self.assertEqual(container.records, {})
                        if blob:
                            self.assertEqual(service.records, {})

    def test_delimiters_and_identity_component_boundaries_cannot_collide(self):
        identities = (("a/b", "c", "d"), ("a", "b/c", "d"), ("a", "b", "c/d"), ("a", "b", "d"))
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                references = [store.save_chat(*identity, {}) for identity in identities]
                self.assertEqual(len(container.records), len(identities) * (1 if blob else 2))
                if blob:
                    self.assertEqual(len(service.records), len(identities))
                store.delete_chat_results(*identities[0])
                for identity, reference in zip(identities[1:], references[1:]):
                    self.assertEqual(store.load_chat(*identity, reference), {})

    def test_chat_quota_counts_complete_canonical_bytes_before_any_write(self):
        result = {"text": "😀" * 20}
        size = len(canonical_bytes(result))
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, max_size_bytes=size - 1)
                with self.assertRaises(store_module.WorkflowResultTooLargeError):
                    self.save(store, result)
                self.assertEqual(container.creates, [])
                if blob:
                    self.assertEqual(service.uploads, [])
                store.max_size_bytes = size
                reference = self.save(store, result)
                store.max_size_bytes = 1
                self.assertEqual(self.load(store, reference), result)

    def test_chat_sdk_read_errors_propagate_without_backend_fallback(self):
        error = ServiceRequestError("Private provider details.")
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                reference = self.save(store)
                container.read_error = error
                for method in (self.load, self.page):
                    with self.assertRaises(ServiceRequestError) as raised:
                        method(store, reference)
                    self.assertIs(raised.exception, error)
                container.read_error = None
                if blob:
                    service.download_error = error
                    for method in (self.load, self.page):
                        with self.assertRaises(ServiceRequestError) as raised:
                            method(store, reference)
                        self.assertIs(raised.exception, error)
                    service.download_error = None
                    service.records.clear()
                    for method in (self.load, self.page):
                        with self.assertRaises(ResourceNotFoundError):
                            method(store, reference)
                    self.assertEqual(len(container.creates), 1)
                else:
                    chunk = next(row for row in container.records.values() if row["record_kind"] == "chunk")
                    del container.records[(self.message_id, chunk["id"])]
                    for method in (self.load, self.page):
                        with self.assertRaises(CosmosResourceNotFoundError):
                            method(store, reference)

    def test_chat_saved_backend_is_not_reselected_when_configuration_changes(self):
        store, container, _ = self.make_store()
        reference = self.save(store)
        service = FakeBlobService()
        configured = store_module.WorkflowResultStore(container, service, "personal-chat", max_size_bytes=1)
        self.assertEqual(self.load(configured, reference), {"text": "saved final"})
        self.assertEqual(service.downloads, [])
        configured.max_size_bytes = 1024
        blob_reference = self.save(configured, {})
        for method in (self.load, self.page):
            with self.assertRaises(store_module.WorkflowResultStorageUnavailableError):
                method(store, blob_reference)
        self.delete(configured)
        self.assertEqual(container.records, {})
        self.assertEqual(service.records, {})

    def test_message_cleanup_sweeps_sections_and_chunks_but_never_published_documents(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, chunk_size_bytes=16)
                reference = self.save(store, {
                    "text": "x" * 17000,
                    "published_documents": [{"id": "published", "blob_path": "published/report.json"}],
                })
                self.save(store, {"diagnostics": ["section"]})
                self.save(store, {"text": "another immutable revision"})
                if not blob:
                    self.assertGreater(reference["chunk_count"], 1000)
                target_rows = set(container.records)
                target_blobs = set(service.records) if blob else set()
                for identity in (
                    ("another-owner", self.conversation_id, self.message_id),
                    (self.user_id, "another-conversation", self.message_id),
                    (self.user_id, self.conversation_id, "another-message"),
                ):
                    store.save_chat(*identity, {"text": "keep"})
                workflow = {"id": self.conversation_id, "user_id": self.user_id}
                store.save(workflow, self.message_id, self.message_id, {"text": "workflow must remain"})
                container.create_item(body={
                    "id": "ordinary-message", "run_id": self.message_id,
                    "user_id": self.user_id, "conversation_id": self.conversation_id,
                    "message_id": self.message_id, "scope_type": "chat", "scope_id": self.conversation_id,
                    "type": "assistant", "item_type": "message",
                })
                if blob:
                    for key in (("personal-chat", "published/report.json"),
                                ("workspace-documents", "published/report.json"),
                                ("personal-chat", "analyze/original-report.json")):
                        service.records[key] = {"data": b"independent", "metadata": {}, "etag": "keep"}
                remaining_rows = {key: json_copy(row) for key, row in container.records.items() if key not in target_rows}
                remaining_blobs = {key: row for key, row in service.records.items() if key not in target_blobs} if blob else {}
                self.delete(store)
                self.assertEqual(container.records, remaining_rows)
                self.assertEqual(set(container.deletes), target_rows)
                query = next(
                    query for query in container.queries
                    if any(parameter == {
                        "name": "@record_type", "value": "chat_analysis_result_chunk",
                    } for parameter in query["parameters"])
                )
                self.assertEqual(query["partition_key"], self.message_id)
                self.assertFalse(query["enable_cross_partition_query"])
                self.assertEqual(query["max_item_count"], 100)
                for forbidden in ("TOP", "SELECT *", "c.payload"):
                    self.assertNotIn(forbidden, query["query"])
                if blob:
                    self.assertEqual(service.records, remaining_blobs)
                    self.assertEqual(set(service.deletes), target_blobs)
                    self.assertTrue(service.lists[-1]["prefix"].endswith(f"{identifier_hash(self.message_id)}/"))
                else:
                    self.assertGreater(len(container.query_pages), 10)
                self.delete(store)
                self.assertEqual(container.records, remaining_rows)

    def test_conversation_cleanup_streams_every_message_partition_without_history_limit(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                for index in range(1005):
                    message_id = self.message_id if index == 0 else f"assistant-{index}"
                    store.save_chat(self.user_id, self.conversation_id, message_id, {"section": index})
                target_rows = set(container.records)
                target_blobs = set(service.records) if blob else set()
                for identity in (
                    ("another-owner", self.conversation_id, self.message_id),
                    (self.user_id, "another-conversation", self.message_id),
                ):
                    store.save_chat(*identity, {"text": "keep"})
                remaining_rows = {key: json_copy(row) for key, row in container.records.items() if key not in target_rows}
                remaining_blobs = {key: row for key, row in service.records.items() if key not in target_blobs} if blob else {}
                self.delete(store, conversation=True)
                self.assertEqual(container.records, remaining_rows)
                self.assertEqual(set(container.deletes), target_rows)
                query = next(
                    query for query in container.queries
                    if any(parameter == {
                        "name": "@record_type", "value": "chat_analysis_result_chunk",
                    } for parameter in query["parameters"])
                )
                self.assertIsNone(query["partition_key"])
                self.assertTrue(query["enable_cross_partition_query"])
                self.assertEqual(query["max_item_count"], 100)
                self.assertGreater(len(container.query_pages), 10)
                values = {parameter["name"]: parameter["value"] for parameter in query["parameters"]}
                self.assertEqual(values, {
                    "@scope_type": "chat", "@scope_id": self.conversation_id,
                    "@user_id": self.user_id, "@conversation_id": self.conversation_id,
                    "@record_type": "chat_analysis_result_chunk",
                })
                for forbidden in ("TOP", "SELECT *", "c.payload"):
                    self.assertNotIn(forbidden, query["query"])
                if blob:
                    self.assertEqual(service.records, remaining_blobs)
                    self.assertEqual(set(service.deletes), target_blobs)
                    self.assertTrue(service.lists[-1]["prefix"].endswith(f"{identifier_hash(self.conversation_id)}/"))
                self.delete(store, conversation=True)
                self.assertEqual(container.records, remaining_rows)

    def test_cleanup_rechecks_cosmos_identity_partition_and_computed_record_ids(self):
        for conversation in (False, True):
            for field, value in (
                ("user_id", "foreign-owner"), ("conversation_id", "foreign-conversation"),
                ("message_id", "foreign-message"), ("run_id", "foreign-run"),
                ("scope_type", "personal"), ("scope_id", "foreign-scope"),
                ("type", "published_document"), ("item_type", "published_document"),
                ("id", "published-document-id"), ("record_kind", "other"), ("chunk_index", -1),
            ):
                with self.subTest(conversation=conversation, field=field):
                    store, container, _ = self.make_store(chunk_size_bytes=16)
                    self.save(store)
                    foreign = json_copy(next(row for row in container.records.values() if row["record_kind"] == "chunk"))
                    foreign[field] = value
                    with patch.object(container, "query_items", return_value=iter([foreign])):
                        with self.assertRaises(store_module.WorkflowResultIntegrityError):
                            self.delete(store, conversation=conversation)
                    self.assertEqual(container.deletes, [])

    def test_cleanup_rejects_foreign_blob_metadata_or_unrecognized_private_paths(self):
        for conversation in (False, True):
            for field in ("scope_hash", "user_hash", "conversation_hash", "run_hash", "message_hash", "path"):
                with self.subTest(conversation=conversation, field=field):
                    store, container, service = self.make_store(blob=True)
                    self.save(store)
                    key = next(iter(service.records))
                    if field == "path":
                        row = service.records.pop(key)
                        service.records[(key[0], key[1].rsplit("/", 1)[0] + "/published.json")] = row
                    else:
                        service.records[key]["metadata"][field] = "0" * 64
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        self.delete(store, conversation=conversation)
                    self.assertEqual(service.deletes, [])
                    self.assertEqual(container.deletes, [])

    def test_blob_etag_changes_block_chat_reads_and_cleanup(self):
        original_properties = FakeBlob.get_blob_properties

        def change_after_properties(blob):
            properties = original_properties(blob)
            blob._row()["etag"] += "-changed"
            return properties

        for operation in ("load", "page", "message-cleanup", "conversation-cleanup"):
            with self.subTest(operation=operation):
                store, container, service = self.make_store(blob=True)
                reference = self.save(store)
                with patch.object(FakeBlob, "get_blob_properties", change_after_properties):
                    with self.assertRaises(ResourceModifiedError):
                        if operation in ("load", "page"):
                            getattr(self, operation)(store, reference)
                        else:
                            self.delete(store, conversation=operation == "conversation-cleanup")
                self.assertEqual(container.deletes, [])
                self.assertEqual(service.deletes, [])

    def test_cleanup_provider_errors_propagate_and_missing_blob_configuration_keeps_manifest(self):
        error = ServiceRequestError("Private cleanup failure.")
        for conversation in (False, True):
            for blob, field in ((True, "list_error"), (True, "delete_error"),
                                (False, "query_error"), (False, "delete_error")):
                with self.subTest(conversation=conversation, blob=blob, field=field):
                    store, container, service = self.make_store(blob=blob)
                    self.save(store)
                    backend = service if blob else container
                    setattr(backend, field, error)
                    with self.assertRaises(ServiceRequestError) as raised:
                        self.delete(store, conversation=conversation)
                    self.assertIs(raised.exception, error)
                    self.assertEqual(container.deletes, [])
                    setattr(backend, field, None)
                    self.delete(store, conversation=conversation)
                    self.assertEqual(container.records, {})
            store, container, service = self.make_store(blob=True)
            self.save(store)
            without_blob = store_module.WorkflowResultStore(container)
            with self.assertRaises(store_module.WorkflowResultStorageUnavailableError):
                self.delete(without_blob, conversation=conversation)
            self.assertEqual(container.deletes, [])
            self.assertEqual(len(container.records), 1)
            self.assertEqual(len(service.records), 1)

    def test_cleanup_tolerates_objects_disappearing_during_conditional_deletion(self):
        for conversation in (False, True):
            with self.subTest(conversation=conversation):
                store, container, service = self.make_store(blob=True)
                self.save(store)
                original_blob_delete = FakeBlob.delete_blob
                original_record_delete = container.delete_item

                def remove_blob_then_report_missing(blob, **kwargs):
                    original_blob_delete(blob, **kwargs)
                    raise ResourceNotFoundError("Already deleted.")

                def remove_record_then_report_missing(**kwargs):
                    original_record_delete(**kwargs)
                    raise CosmosResourceNotFoundError(status_code=404, message="Already deleted.")

                with patch.object(FakeBlob, "delete_blob", remove_blob_then_report_missing), patch.object(
                    container, "delete_item", remove_record_then_report_missing,
                ):
                    self.delete(store, conversation=conversation)
                self.assertEqual(container.records, {})
                self.assertEqual(service.records, {})

    def test_lazy_configured_api_uses_personal_chunks_even_when_workflows_are_disabled(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                personal = FakeCosmosContainer()
                settings = FakeCosmosContainer()
                settings.create_item(body={
                    "id": "app_settings", "run_id": "app_settings", "enable_workflows": False,
                    "max_generated_chat_artifact_size_mb": 1,
                })
                service = FakeBlobService() if blob else None
                config = SimpleNamespace(
                    CLIENTS={"storage_account_office_docs_client": service} if blob else {},
                    cosmos_personal_workflow_run_items_container=personal,
                    cosmos_settings_container=settings,
                    storage_account_personal_chat_container_name="configured-chat",
                )
                identity = (self.user_id, self.conversation_id, self.message_id)
                with patch.dict(sys.modules, {"config": config}):
                    reference = store_module.save_chat_analysis_result(*identity, {"text": "configured"})
                    self.assertEqual(settings.reads, [("app_settings", "app_settings")])
                    settings.read_error = AssertionError("Reads/cleanup must not depend on write settings.")
                    self.assertEqual(
                        store_module.load_chat_analysis_result(*identity, reference), {"text": "configured"},
                    )
                    page = store_module.read_chat_analysis_result_page(*identity, reference, offset=1, limit=2)
                    self.assertEqual(page["content"], canonical_bytes({"text": "configured"})[1:3].decode("ascii"))
                    store_module.save_chat_analysis_result(
                        self.user_id, self.conversation_id, "second-message", {}, settings={},
                    )
                    store_module.delete_chat_analysis_results(*identity)
                    self.assertTrue(personal.records)
                    store_module.delete_chat_analysis_results(self.user_id, self.conversation_id)
                    self.assertEqual(personal.records, {})
                    self.assertEqual(settings.reads, [("app_settings", "app_settings")])
                    if blob:
                        self.assertEqual(service.records, {})
                        self.assertTrue(all(upload["key"][0] == "configured-chat" for upload in service.uploads))

    def test_configured_chat_write_failures_and_invalid_quotas_never_fall_back(self):
        personal = FakeCosmosContainer()
        service = FakeBlobService()
        config = SimpleNamespace(
            CLIENTS={"storage_account_office_docs_client": service},
            cosmos_personal_workflow_run_items_container=personal,
            storage_account_personal_chat_container_name="configured-chat",
        )
        identity = (self.user_id, self.conversation_id, self.message_id)
        error = ServiceRequestError("Configured Blob failed.")
        with patch.dict(sys.modules, {"config": config}):
            service.upload_error = error
            with self.assertRaises(ServiceRequestError) as raised:
                store_module.save_chat_analysis_result(*identity, {}, settings={})
            self.assertIs(raised.exception, error)
            self.assertEqual(personal.creates, [])
            for quota in (True, None, 0, -1, "bad", 1.5):
                with self.subTest(quota=quota):
                    with self.assertRaises(ValueError):
                        store_module.save_chat_analysis_result(
                            *identity, {}, settings={"max_generated_chat_artifact_size_mb": quota},
                        )
            with self.assertRaises(store_module.WorkflowResultTooLargeError):
                store_module.save_chat_analysis_result(
                    *identity, {"text": "x" * (1024 * 1024)},
                    settings={"max_generated_chat_artifact_size_mb": "1"},
                )
            self.assertEqual(len(service.uploads), 1)
            self.assertEqual(personal.creates, [])

    def test_chat_public_api_signatures_are_stable(self):
        signatures = {
            "save_chat_analysis_result": [
                "user_id", "conversation_id", "message_id", "result", "settings",
                "guard_token", "require_analysis_guard",
            ],
            "load_chat_analysis_result": ["user_id", "conversation_id", "message_id", "reference"],
            "read_chat_analysis_result_page": ["user_id", "conversation_id", "message_id", "reference", "offset", "limit"],
            "delete_chat_analysis_results": ["user_id", "conversation_id", "message_id"],
        }
        for name, parameters in signatures.items():
            self.assertEqual(list(inspect.signature(getattr(store_module, name)).parameters), parameters)
        guard_parameters = inspect.signature(store_module.save_chat_analysis_result).parameters
        self.assertIsNone(guard_parameters["guard_token"].default)
        self.assertIs(guard_parameters["require_analysis_guard"].default, False)
        self.assertEqual(guard_parameters["guard_token"].kind, inspect.Parameter.KEYWORD_ONLY)
        for method in (store_module.read_chat_analysis_result_page, store_module.WorkflowResultStore.read_chat_page):
            signature = inspect.signature(method)
            self.assertEqual(signature.parameters["offset"].default, 0)
            self.assertEqual(signature.parameters["limit"].default, 65536)
            self.assertEqual(signature.parameters["limit"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(
            inspect.signature(store_module.save_chat_analysis_result).parameters["settings"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        for method in (store_module.delete_chat_analysis_results, store_module.WorkflowResultStore.delete_chat_results):
            self.assertIsNone(inspect.signature(method).parameters["message_id"].default)


class OrchestrationAnalysisResultStoreTests(unittest.TestCase):
    make_store = staticmethod(make_store)

    def setUp(self):
        self.user_id = "original-owner"
        self.conversation_id = "conversation/../#one"
        self.run_id = "orchestration-run/../#one"
        self.step_id = "analyze-step/../#one"
        self.identity = (self.user_id, self.conversation_id, self.run_id, self.step_id)

    def save(self, store, result=None):
        return store.save_orchestration(*self.identity, {"text": "saved final"} if result is None else result)

    def load(self, store, reference):
        return store.load_orchestration(*self.identity, reference)

    def page(self, store, reference, **kwargs):
        return store.read_orchestration_page(*self.identity, reference, **kwargs)

    def delete(self, store, *, conversation=False):
        return store.delete_orchestration_results(
            self.user_id, self.conversation_id, None if conversation else self.run_id,
        )

    def test_real_run_and_step_binding_has_no_workflow_task_or_message_identity(self):
        result = {"text": "🧪 中文 café" * 1000, "records": [None, False, 1.25]}
        identity = {
            "scope_type": "orchestration", "scope_id": self.conversation_id,
            "user_id": self.user_id, "conversation_id": self.conversation_id,
            "run_id": self.run_id, "step_id": self.step_id,
        }
        token = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, chunk_size_bytes=1024)
                reference = self.save(store, result)
                self.assertEqual(set(reference), {"storage", "schema_version", "sha256", "size_bytes", "chunk_count"})
                self.assertEqual(reference["sha256"], hashlib.sha256(canonical_bytes(result)).hexdigest())
                self.assertEqual(reference["size_bytes"], len(canonical_bytes(result)))
                self.assertEqual(reference["schema_version"], 1)
                self.assertEqual(reference["storage"], "blob" if blob else "cosmos")
                fresh_store = store_module.WorkflowResultStore(container, service, "personal-chat")
                self.assertEqual(self.load(fresh_store, reference), result)
                for (partition, record_id), row in container.records.items():
                    self.assertEqual(partition, self.run_id)
                    for key, value in identity.items():
                        self.assertEqual(row[key], value)
                    for forbidden in ("workflow_id", "task_id", "message_id"):
                        self.assertNotIn(forbidden, row)
                    self.assertEqual(row["type"], "orchestration_analysis_result_chunk")
                    self.assertEqual(row["item_type"], "orchestration_analysis_result_chunk")
                    self.assertTrue(record_id.startswith(
                        f"orchestration-analysis-result:v1:{token}:{reference['storage']}:{reference['sha256']}:",
                    ))
                if blob:
                    name = (
                        f"orchestration-analysis-results/v1/orchestration/{identifier_hash(self.user_id)}/"
                        f"{identifier_hash(self.conversation_id)}/{identifier_hash(self.run_id)}/"
                        f"{identifier_hash(self.step_id)}/{reference['sha256']}.json"
                    )
                    self.assertEqual(set(service.records), {("personal-chat", name)})
                    self.assertEqual(service.records[("personal-chat", name)]["metadata"], {
                        "schema_version": "1", "scope_type": "orchestration",
                        "scope_hash": identifier_hash(self.conversation_id),
                        "user_hash": identifier_hash(self.user_id),
                        "conversation_hash": identifier_hash(self.conversation_id),
                        "run_hash": identifier_hash(self.run_id), "step_hash": identifier_hash(self.step_id),
                        "sha256": reference["sha256"], "size_bytes": str(reference["size_bytes"]),
                        "media_type": "application/json",
                    })

    def test_replay_multiple_steps_sections_and_revisions_are_immutable(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, chunk_size_bytes=16)
                first = self.save(store, {"text": "first", "records": [1, 2]})
                snapshot = json_copy(list(container.records.values()))
                self.assertEqual(self.save(store, {"records": [1, 2], "text": "first"}), first)
                self.assertEqual(list(container.records.values()), snapshot)
                revised = self.save(store, {"text": "revision"})
                diagnostics = self.save(store, {"diagnostics": ["private notes"]})
                other_step = store.save_orchestration(
                    self.user_id, self.conversation_id, self.run_id, "another-step", {"text": "revision"},
                )
                self.assertEqual(self.load(store, first), {"text": "first", "records": [1, 2]})
                self.assertEqual(self.load(store, revised), {"text": "revision"})
                self.assertEqual(self.load(store, diagnostics), {"diagnostics": ["private notes"]})
                self.assertEqual(other_step, revised)
                self.assertEqual(
                    store.load_orchestration(self.user_id, self.conversation_id, self.run_id, "another-step", other_step),
                    {"text": "revision"},
                )
                if blob:
                    self.assertEqual(len(service.records), 4)
                    self.assertTrue(all(upload["overwrite"] is False for upload in service.uploads))

    def test_foreign_owner_conversation_run_step_or_storage_kind_cannot_read(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, service = self.make_store(blob=blob)
                reference = self.save(store)
                for index in range(4):
                    foreign = list(self.identity)
                    foreign[index] = f"foreign-{index}"
                    for method in (store.load_orchestration, store.read_orchestration_page):
                        with self.assertRaises(CosmosResourceNotFoundError):
                            method(*foreign, reference)
                for method in (store.load_chat, store.read_chat_page):
                    with self.assertRaises(CosmosResourceNotFoundError):
                        method(self.user_id, self.conversation_id, self.run_id, reference)
                workflow = {"id": self.conversation_id, "user_id": self.user_id}
                for method in (store.load, store.read_page):
                    with self.assertRaises(CosmosResourceNotFoundError):
                        method(workflow, self.run_id, self.step_id, reference)
                if blob:
                    self.assertEqual(service.downloads, [])

    def test_workflow_chat_and_orchestration_with_identical_values_remain_independent(self):
        workflow = {"id": self.conversation_id, "user_id": self.user_id}
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, _, _ = self.make_store(blob=blob)
                reference = self.save(store, {})
                self.assertEqual(store.save_chat(self.user_id, self.conversation_id, self.run_id, {}), reference)
                self.assertEqual(store.save(workflow, self.run_id, self.step_id, {}), reference)
                self.delete(store, conversation=True)
                self.assertEqual(store.load_chat(self.user_id, self.conversation_id, self.run_id, reference), {})
                self.assertEqual(store.load(workflow, self.run_id, self.step_id, reference), {})
                self.save(store, {})
                store.delete_chat_results(self.user_id, self.conversation_id)
                self.assertEqual(self.load(store, reference), {})
                store.delete_run_results(workflow, self.run_id)
                self.assertEqual(self.load(store, reference), {})

    def test_every_stored_orchestration_manifest_and_chunk_identity_field_is_checked(self):
        fields = {
            "user_id": "foreign", "conversation_id": "foreign", "run_id": "foreign", "step_id": "foreign",
            "scope_type": "chat", "scope_id": "foreign", "type": "orchestration_step",
            "item_type": "orchestration_step", "id": "foreign",
        }
        for blob, kind in ((False, "manifest"), (False, "chunk"), (True, "manifest")):
            for field, value in fields.items():
                with self.subTest(blob=blob, kind=kind, field=field):
                    store, container, service = self.make_store(blob=blob)
                    reference = self.save(store)
                    row = next(row for row in container.records.values() if row["record_kind"] == kind)
                    row[field] = value
                    for method in (self.load, self.page):
                        with self.assertRaises(store_module.WorkflowResultIntegrityError):
                            method(store, reference)
                    if blob:
                        self.assertEqual(service.downloads, [])

    def test_blob_binding_metadata_is_verified_before_read_replay_and_cleanup(self):
        for conversation in (False, True):
            for field in (
                "schema_version", "scope_type", "scope_hash", "user_hash", "conversation_hash",
                "run_hash", "step_hash", "sha256", "media_type",
            ):
                with self.subTest(conversation=conversation, field=field):
                    store, container, service = self.make_store(blob=True)
                    reference = self.save(store)
                    next(iter(service.records.values()))["metadata"][field] = "foreign"
                    for method in (self.load, self.page):
                        with self.assertRaises(store_module.WorkflowResultIntegrityError):
                            method(store, reference)
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        self.save(store)
                    with self.assertRaises(store_module.WorkflowResultIntegrityError):
                        self.delete(store, conversation=conversation)
                    self.assertEqual(service.downloads, [])
                    self.assertEqual(service.deletes, [])
                    self.assertEqual(container.deletes, [])

    def test_invalid_ids_and_path_bearing_references_fail_before_io_or_configuration(self):
        store, container, service = self.make_store(blob=True)
        reference = {"storage": "blob", "schema_version": 1, "sha256": "a" * 64, "size_bytes": 2, "chunk_count": 0}
        methods = (
            (store.save_orchestration, ({},)), (store.load_orchestration, (reference,)),
            (store.read_orchestration_page, (reference,)),
            (store_module.save_orchestration_analysis_result, ({},)),
            (store_module.load_orchestration_analysis_result, (reference,)),
            (store_module.read_orchestration_analysis_result_page, (reference,)),
        )
        with patch.object(store_module, "_configured_result_store", side_effect=AssertionError("Unexpected config access.")):
            for index in range(4):
                for invalid in (None, "", True, 42, {}, "x" * 1025, "😀" * 257):
                    identity = list(self.identity)
                    identity[index] = invalid
                    with self.subTest(index=index, invalid_type=type(invalid).__name__):
                        for method, arguments in methods:
                            with self.assertRaises(ValueError):
                                method(*identity, *arguments)
                        if index < 3 and not (index == 2 and invalid is None):
                            for method in (
                                store.delete_orchestration_results, store_module.delete_orchestration_analysis_results,
                            ):
                                with self.assertRaises(ValueError):
                                    method(*identity[:3])
        for extra in (
            {"blob_path": "published/report.json"}, {"url": "https://provider.invalid/private"},
            {"workflow_id": "invented"}, {"task_id": "invented"}, {"message_id": "not-created"},
            {"step_id": self.step_id},
        ):
            for method in (self.load, self.page):
                with self.assertRaises(ValueError):
                    method(store, {**reference, **extra})
        self.assertEqual(container.reads, [])
        self.assertEqual(container.creates, [])
        self.assertEqual(container.queries, [])
        self.assertEqual(service.uploads, [])
        self.assertEqual(service.lists, [])

    def test_orchestration_pages_remain_bounded_serialized_transport(self):
        result = {"records": [{"text": "😀中文\\\""}] * 20}
        expected = canonical_bytes(result)
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob, chunk_size_bytes=32)
                reference = self.save(store, result)
                container.reads.clear()
                page = self.page(store, reference, offset=29, limit=10)
                self.assertEqual(page["content"].encode("ascii"), expected[29:39])
                self.assertFalse(page["integrity"]["full_sha256_verified"])
                if blob:
                    self.assertEqual([(call["offset"], call["length"]) for call in service.downloads], [(29, 10)])
                else:
                    chunks = [container.records[key]["chunk_index"] for key in container.reads
                              if container.records[key]["record_kind"] == "chunk"]
                    self.assertEqual(chunks, [0, 1])
                offset, contents = 0, []
                while offset is not None:
                    page = self.page(store, reference, offset=offset, limit=13)
                    contents.append(page["content"])
                    offset = page["next_offset"]
                self.assertEqual("".join(contents).encode("ascii"), expected)
                self.assertTrue(page["complete"])
                self.assertFalse(page["integrity"]["full_sha256_verified"])
                self.assertTrue(self.page(store, reference)["integrity"]["full_sha256_verified"])
                for arguments in ({"offset": True}, {"limit": 0}, {"limit": store_module.MAX_PAGE_BYTES + 1}):
                    container.reads.clear()
                    with self.assertRaises(ValueError):
                        self.page(store, reference, **arguments)
                    self.assertEqual(container.reads, [])

    def test_interrupted_orchestration_sections_resume_or_sweep_without_a_manifest(self):
        result = {"text": "x" * 200}
        for blob in (False, True):
            for retry in (False, True):
                for conversation in (False, True):
                    with self.subTest(blob=blob, retry=retry, conversation=conversation):
                        store, container, service = self.make_store(blob=blob, chunk_size_bytes=16)
                        container.fail_create_at = 1 if blob else 2
                        error = ServiceRequestError("Interrupted provider write.")
                        container.create_error = error
                        with self.assertRaises(ServiceRequestError) as raised:
                            self.save(store, result)
                        self.assertIs(raised.exception, error)
                        self.assertFalse(any(row["record_kind"] == "manifest" for row in container.records.values()))
                        reference = {
                            "storage": "blob" if blob else "cosmos", "schema_version": 1,
                            "sha256": hashlib.sha256(canonical_bytes(result)).hexdigest(),
                            "size_bytes": len(canonical_bytes(result)),
                            "chunk_count": 0 if blob else (len(canonical_bytes(result)) + 15) // 16,
                        }
                        for method in (self.load, self.page):
                            with self.assertRaises(CosmosResourceNotFoundError):
                                method(store, reference)
                        if retry:
                            container.fail_create_at = None
                            self.assertEqual(self.save(store, result), reference)
                            self.assertEqual(self.load(store, reference), result)
                        self.delete(store, conversation=conversation)
                        self.assertEqual(container.records, {})
                        if blob:
                            self.assertEqual(service.records, {})

    def test_cleanup_streams_all_steps_sections_and_runs_without_touching_other_lifecycles(self):
        for blob in (False, True):
            for conversation in (False, True):
                with self.subTest(blob=blob, conversation=conversation):
                    store, container, service = self.make_store(blob=blob)
                    for index in range(1005):
                        run_id = "second-target-run" if conversation and index % 2 else self.run_id
                        step_id = self.step_id if index == 0 else f"step-{index}"
                        store.save_orchestration(self.user_id, self.conversation_id, run_id, step_id, {"section": index})
                    self.save(store, {"diagnostics": ["another section"]})
                    self.save(store, {"text": "another revision", "published_blob": "published/report.json"})
                    target_rows = set(container.records)
                    target_blobs = set(service.records) if blob else set()
                    foreign = [
                        ("another-owner", self.conversation_id, self.run_id, self.step_id),
                        (self.user_id, "another-conversation", self.run_id, self.step_id),
                    ]
                    if not conversation:
                        foreign.append((self.user_id, self.conversation_id, "another-run", self.step_id))
                    for identity in foreign:
                        store.save_orchestration(*identity, {"text": "keep"})
                    store.save_chat(self.user_id, self.conversation_id, self.run_id, {"text": "keep chat"})
                    store.save(
                        {"id": self.conversation_id, "user_id": self.user_id},
                        self.run_id, self.step_id, {"text": "keep workflow"},
                    )
                    container.create_item(body={
                        "id": "visible-orchestration-step", "run_id": self.run_id, "step_id": self.step_id,
                        "scope_type": "orchestration", "scope_id": self.conversation_id,
                        "user_id": self.user_id, "conversation_id": self.conversation_id,
                        "type": "orchestration_step", "item_type": "orchestration_step",
                    })
                    if blob:
                        for key in (("personal-chat", "published/report.json"), ("workspace-documents", "published/report.json")):
                            service.records[key] = {"data": b"independent", "metadata": {}, "etag": "keep"}
                    remaining_rows = {key: json_copy(row) for key, row in container.records.items() if key not in target_rows}
                    remaining_blobs = {key: row for key, row in service.records.items() if key not in target_blobs} if blob else {}
                    self.delete(store, conversation=conversation)
                    self.assertEqual(container.records, remaining_rows)
                    self.assertEqual(set(container.deletes), target_rows)
                    self.assertGreater(len(container.query_pages), 10)
                    query = next(
                        query for query in container.queries
                        if any(parameter == {
                            "name": "@record_type", "value": "orchestration_analysis_result_chunk",
                        } for parameter in query["parameters"])
                    )
                    self.assertEqual(query["partition_key"], None if conversation else self.run_id)
                    self.assertEqual(query["enable_cross_partition_query"], conversation)
                    self.assertEqual(query["max_item_count"], 100)
                    self.assertIn("c.step_id", query["query"])
                    for forbidden in ("TOP", "SELECT *", "c.payload", "c.workflow_id", "c.task_id", "c.message_id"):
                        self.assertNotIn(forbidden, query["query"])
                    expected_parameters = {
                        "@scope_type": "orchestration", "@scope_id": self.conversation_id,
                        "@user_id": self.user_id, "@conversation_id": self.conversation_id,
                        "@record_type": "orchestration_analysis_result_chunk",
                    }
                    if not conversation:
                        expected_parameters["@run_id"] = self.run_id
                    self.assertEqual(
                        {parameter["name"]: parameter["value"] for parameter in query["parameters"]}, expected_parameters,
                    )
                    if blob:
                        self.assertEqual(service.records, remaining_blobs)
                        self.assertEqual(set(service.deletes), target_blobs)
                        self.assertTrue(service.lists[-1]["prefix"].endswith(
                            f"{identifier_hash(self.conversation_id if conversation else self.run_id)}/",
                        ))
                    self.delete(store, conversation=conversation)
                    self.assertEqual(container.records, remaining_rows)

    def test_cleanup_rechecks_returned_identity_and_rejects_unrecognized_private_paths(self):
        for conversation in (False, True):
            for field, value in (
                ("user_id", "foreign"), ("conversation_id", "foreign"), ("run_id", "foreign"),
                ("step_id", "foreign"), ("scope_type", "chat"), ("scope_id", "foreign"),
                ("type", "orchestration_step"), ("item_type", "orchestration_step"),
                ("id", "published-document-id"), ("sha256", "a" * 64),
            ):
                with self.subTest(conversation=conversation, field=field):
                    store, container, _ = self.make_store()
                    self.save(store)
                    foreign = json_copy(next(iter(container.records.values())))
                    foreign[field] = value
                    with patch.object(container, "query_items", return_value=iter([foreign])):
                        with self.assertRaises(store_module.WorkflowResultIntegrityError):
                            self.delete(store, conversation=conversation)
                    self.assertEqual(container.deletes, [])
            store, container, service = self.make_store(blob=True)
            self.save(store)
            key = next(iter(service.records))
            row = service.records.pop(key)
            service.records[(key[0], key[1].rsplit("/", 1)[0] + "/published.json")] = row
            with self.assertRaises(store_module.WorkflowResultIntegrityError):
                self.delete(store, conversation=conversation)
            self.assertEqual(service.deletes, [])
            self.assertEqual(container.deletes, [])

    def test_orchestration_reads_and_cleanup_are_bound_to_verified_blob_etags(self):
        original_properties = FakeBlob.get_blob_properties

        def change_after_properties(blob):
            properties = original_properties(blob)
            blob._row()["etag"] += "-changed"
            return properties

        for operation in ("load", "page", "run-cleanup", "conversation-cleanup"):
            with self.subTest(operation=operation):
                store, container, service = self.make_store(blob=True)
                reference = self.save(store)
                with patch.object(FakeBlob, "get_blob_properties", change_after_properties):
                    with self.assertRaises(ResourceModifiedError):
                        if operation in ("load", "page"):
                            getattr(self, operation)(store, reference)
                        else:
                            self.delete(store, conversation=operation == "conversation-cleanup")
                self.assertEqual(container.deletes, [])
                self.assertEqual(service.deletes, [])

    def test_lazy_configured_apis_need_no_workflow_or_message_or_step_list_container(self):
        for blob in (False, True):
            with self.subTest(blob=blob):
                personal = FakeCosmosContainer()
                settings = FakeCosmosContainer()
                settings.create_item(body={
                    "id": "app_settings", "run_id": "app_settings", "enable_workflows": False,
                    "max_generated_chat_artifact_size_mb": 1,
                })
                service = FakeBlobService() if blob else None
                config = SimpleNamespace(
                    CLIENTS={"storage_account_office_docs_client": service} if blob else {},
                    cosmos_personal_workflow_run_items_container=personal,
                    cosmos_settings_container=settings,
                    storage_account_personal_chat_container_name="configured-chat",
                )
                with patch.dict(sys.modules, {"config": config}):
                    reference = store_module.save_orchestration_analysis_result(*self.identity, {"text": "configured"})
                    self.assertEqual(settings.reads, [("app_settings", "app_settings")])
                    settings.read_error = AssertionError("Read/cleanup must not fetch write settings.")
                    self.assertEqual(
                        store_module.load_orchestration_analysis_result(*self.identity, reference), {"text": "configured"},
                    )
                    page = store_module.read_orchestration_analysis_result_page(*self.identity, reference, offset=1, limit=2)
                    self.assertEqual(page["content"], canonical_bytes({"text": "configured"})[1:3].decode("ascii"))
                    store_module.save_orchestration_analysis_result(
                        self.user_id, self.conversation_id, self.run_id, "another-step", {}, {},
                    )
                    store_module.save_orchestration_analysis_result(
                        self.user_id, self.conversation_id, "another-run", self.step_id, {}, settings={},
                    )
                    store_module.delete_orchestration_analysis_results(self.user_id, self.conversation_id, self.run_id)
                    self.assertTrue(personal.records)
                    self.assertTrue(all(row["run_id"] == "another-run" for row in personal.records.values()))
                    store_module.delete_orchestration_analysis_results(self.user_id, self.conversation_id)
                    self.assertEqual(personal.records, {})
                    self.assertEqual(settings.reads, [("app_settings", "app_settings")])
                    if blob:
                        self.assertEqual(service.records, {})
                        self.assertTrue(all(upload["key"][0] == "configured-chat" for upload in service.uploads))

    def test_configured_orchestration_blob_errors_and_quota_do_not_fall_back(self):
        personal = FakeCosmosContainer()
        service = FakeBlobService()
        config = SimpleNamespace(
            CLIENTS={"storage_account_office_docs_client": service},
            cosmos_personal_workflow_run_items_container=personal,
            storage_account_personal_chat_container_name="configured-chat",
        )
        error = ServiceRequestError("Configured provider failed.")
        with patch.dict(sys.modules, {"config": config}):
            service.upload_error = error
            with self.assertRaises(ServiceRequestError) as raised:
                store_module.save_orchestration_analysis_result(*self.identity, {}, settings={})
            self.assertIs(raised.exception, error)
            self.assertEqual(personal.creates, [])
            with self.assertRaises(store_module.WorkflowResultTooLargeError):
                store_module.save_orchestration_analysis_result(
                    *self.identity, {"text": "x" * (1024 * 1024)},
                    settings={"max_generated_chat_artifact_size_mb": "1"},
                )
            self.assertEqual(len(service.uploads), 1)
            service.upload_error = None
            personal.fail_create_at = 1
            personal.create_error = error
            with self.assertRaises(ServiceRequestError) as raised:
                store_module.save_orchestration_analysis_result(*self.identity, {}, settings={})
            self.assertIs(raised.exception, error)
            self.assertEqual(personal.records, {})
            self.assertEqual(len(service.records), 1)
            store_module.delete_orchestration_analysis_results(self.user_id, self.conversation_id)
            self.assertEqual(service.records, {})

    def test_backend_removal_and_provider_errors_preserve_expected_failure_boundaries(self):
        error = ServiceRequestError("Private provider failure.")
        for blob, field in (
            (True, "download_error"), (True, "list_error"), (True, "delete_error"),
            (False, "read_error"), (False, "query_error"), (False, "delete_error"),
        ):
            with self.subTest(blob=blob, field=field):
                store, container, service = self.make_store(blob=blob)
                reference = self.save(store)
                backend = service if blob else container
                setattr(backend, field, error)
                if field in ("download_error", "read_error"):
                    for method in (self.load, self.page):
                        with self.assertRaises(ServiceRequestError) as raised:
                            method(store, reference)
                        self.assertIs(raised.exception, error)
                else:
                    with self.assertRaises(ServiceRequestError) as raised:
                        self.delete(store, conversation=True)
                    self.assertIs(raised.exception, error)
                self.assertEqual(container.deletes, [])
                setattr(backend, field, None)
                self.delete(store)
                self.assertEqual(container.records, {})
        store, container, service = self.make_store(blob=True)
        reference = self.save(store)
        without_blob = store_module.WorkflowResultStore(container)
        for method in (self.load, self.page):
            with self.assertRaises(store_module.WorkflowResultStorageUnavailableError):
                method(without_blob, reference)
        for conversation in (False, True):
            with self.assertRaises(store_module.WorkflowResultStorageUnavailableError):
                self.delete(without_blob, conversation=conversation)
        self.assertEqual(container.deletes, [])
        self.assertEqual(len(container.records), 1)
        self.assertEqual(len(service.records), 1)

    def test_large_payload_only_returns_a_small_checkpoint_safe_reference(self):
        result = {"text": "x" * (8 * 1024 * 1024 + 128)}
        for blob in (False, True):
            with self.subTest(blob=blob):
                store, container, service = self.make_store(blob=blob)
                reference = self.save(store, result)
                self.assertGreater(reference["size_bytes"], 8 * 1024 * 1024)
                checkpoint = json.dumps({"result_ref": reference, "run_id": self.run_id, "step_id": self.step_id})
                self.assertLess(len(checkpoint.encode("ascii")), 1024)
                restored_reference = json.loads(checkpoint)["result_ref"]
                fresh_store = store_module.WorkflowResultStore(container, service, "personal-chat", max_size_bytes=1)
                self.assertEqual(self.load(fresh_store, restored_reference), result)

    def test_orchestration_api_names_signatures_and_page_limits_are_stable(self):
        functions = {
            "save_orchestration_analysis_result": [
                "user_id", "conversation_id", "run_id", "step_id", "result", "settings",
                "guard_token", "require_analysis_guard",
            ],
            "load_orchestration_analysis_result": ["user_id", "conversation_id", "run_id", "step_id", "reference"],
            "read_orchestration_analysis_result_page": [
                "user_id", "conversation_id", "run_id", "step_id", "reference", "offset", "limit",
            ],
            "delete_orchestration_analysis_results": ["user_id", "conversation_id", "run_id"],
        }
        methods = {
            "save_orchestration": [
                "self", "user_id", "conversation_id", "run_id", "step_id", "result",
                "guard_token", "require_analysis_guard",
            ],
            "load_orchestration": ["self", "user_id", "conversation_id", "run_id", "step_id", "reference"],
            "read_orchestration_page": ["self", "user_id", "conversation_id", "run_id", "step_id", "reference", "offset", "limit"],
            "delete_orchestration_results": ["self", "user_id", "conversation_id", "run_id"],
        }
        for owner, signatures in ((store_module, functions), (store_module.WorkflowResultStore, methods)):
            for name, parameters in signatures.items():
                self.assertEqual(list(inspect.signature(getattr(owner, name)).parameters), parameters)
        for method in (store_module.save_orchestration_analysis_result, store_module.WorkflowResultStore.save_orchestration):
            guard_parameters = inspect.signature(method).parameters
            self.assertIsNone(guard_parameters["guard_token"].default)
            self.assertIs(guard_parameters["require_analysis_guard"].default, False)
            self.assertEqual(guard_parameters["guard_token"].kind, inspect.Parameter.KEYWORD_ONLY)
        for method in (
            store_module.read_orchestration_analysis_result_page, store_module.WorkflowResultStore.read_orchestration_page,
        ):
            signature = inspect.signature(method)
            self.assertEqual(signature.parameters["offset"].default, 0)
            self.assertEqual(signature.parameters["limit"].default, 65536)
            self.assertEqual(signature.parameters["offset"].kind, inspect.Parameter.KEYWORD_ONLY)
        for method in (
            store_module.delete_orchestration_analysis_results, store_module.WorkflowResultStore.delete_orchestration_results,
        ):
            self.assertIsNone(inspect.signature(method).parameters["run_id"].default)


if __name__ == "__main__":
    unittest.main()
