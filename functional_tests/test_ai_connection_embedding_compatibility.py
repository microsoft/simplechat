# test_ai_connection_embedding_compatibility.py
"""
Functional coverage for embedding vector-space activation and persistence guards.
Version: 0.261.125
Implemented in: 0.261.106
Idempotent admin schema observations and conditional revisions: 0.261.125

Use isolated stores to prove that populated vectors, unavailable inspections, and
stale work cannot silently cross embedding profiles or bypass a cleared default.
"""

import copy
import json
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from azure.core.exceptions import ServiceRequestError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.app_stubs import import_app_module
from app_settings_store import AppSettingsStore, SETTINGS_REVISION_FIELD
from test_app_settings_store_consistency import FakeCosmos, FakeRedis
from test_ai_connection_embedding_runtime import custom_settings, runtime
from test_data_management_search_write_fence import FakeGateContainer
from functions_ai_connections import AIConnectionError, EMBEDDING_SELECTION_KEY
from functions_embedding_profile import EMBEDDING_VECTOR_PROFILE_KEY, resolve_embedding_profile
import functions_data_management_search_write_fence as gates


compatibility = import_app_module("functions_embedding_compatibility")


def index_schema(dimensions=3, *, provenance=True, ocr_dimensions=None):
    fields = [
        types.SimpleNamespace(name="embedding", vector_search_dimensions=dimensions),
        types.SimpleNamespace(name="video_ocr_embedding", vector_search_dimensions=ocr_dimensions or dimensions),
    ]
    if provenance:
        fields.append(types.SimpleNamespace(name="embedding_profile_id", vector_search_dimensions=None))
    return types.SimpleNamespace(name="simplechat-user-index", fields=fields)


class EmbeddingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.current = custom_settings()
        self.profile = resolve_embedding_profile(self.current)
        self.current[EMBEDDING_VECTOR_PROFILE_KEY] = self.profile.as_state()
        self.candidate = copy.deepcopy(self.current)
        self.candidate["model_endpoints"][0]["models"][0]["modelName"] = "another-encoder"
        self.next_profile = resolve_embedding_profile(self.candidate)
        self.index_client = Mock()
        self.index_client.get_index.return_value = index_schema()
        self.documents = Mock()
        self.documents.get_document_count.return_value = 0
        self.index_client.get_search_client.return_value.__enter__ = Mock(return_value=self.documents)
        self.index_client.get_search_client.return_value.__exit__ = Mock(return_value=False)
        self.facts = Mock()
        self.facts.query_items.return_value = []
        self.gate = FakeGateContainer()

    def inspect(self, **kwargs):
        return compatibility.inspect_empty_embedding_stores(
            self.candidate, self.next_profile, index_client=self.index_client,
            facts_container=self.facts, **kwargs,
        )

    def test_same_dimensions_different_model_is_blocked_on_populated_search(self):
        self.documents.get_document_count.return_value = 1
        with self.assertRaises(AIConnectionError) as raised:
            self.inspect()
        self.assertEqual(raised.exception.code, "embedding_rebuild_required")
        self.assertEqual(self.next_profile.dimensions, self.profile.dimensions)

    def test_fact_vectors_block_switch_even_when_document_indexes_are_empty(self):
        self.facts.query_items.return_value = [{"id": "existing-fact"}]
        with self.assertRaises(AIConnectionError) as raised:
            self.inspect()
        self.assertEqual(raised.exception.code, "embedding_rebuild_required")

    def test_all_three_scopes_are_inspected_before_activation(self):
        self.inspect()
        self.assertEqual(self.index_client.get_index.call_count, 3)
        self.assertEqual(self.documents.get_document_count.call_count, 3)
        self.facts.query_items.assert_called_once()

    def test_failed_service_inspection_is_not_treated_as_empty(self):
        self.index_client.get_index.side_effect = ServiceRequestError("private endpoint details")
        with self.assertRaises(AIConnectionError) as raised:
            self.inspect()
        self.assertEqual(raised.exception.code, "embedding_compatibility_unavailable")
        self.assertNotIn("private endpoint", str(raised.exception))

    def test_dimension_mismatch_including_reserved_ocr_field_requires_recreation(self):
        for schema in (index_schema(dimensions=4), index_schema(ocr_dimensions=4)):
            with self.subTest(schema=schema):
                self.index_client.get_index.return_value = schema
                with self.assertRaises(AIConnectionError) as raised:
                    self.inspect()
                self.assertEqual(raised.exception.code, "embedding_dimensions_mismatch")

    def test_clear_preserves_baseline_and_cannot_be_used_to_bypass_rebuild(self):
        cleared = copy.deepcopy(self.current)
        cleared[EMBEDDING_SELECTION_KEY] = {"endpoint_id": "", "model_id": "", "provider": ""}
        cleared[EMBEDDING_VECTOR_PROFILE_KEY] = {"id": "forged-baseline"}
        with compatibility.embedding_settings_write_guard(self.current, cleared):
            pass
        self.assertEqual(cleared[EMBEDDING_VECTOR_PROFILE_KEY], self.profile.as_state())
        with (
            patch.object(compatibility, "inspect_empty_embedding_stores", side_effect=AIConnectionError("Rebuild required")) as inspect,
            patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)),
        ):
            with self.assertRaises(AIConnectionError):
                compatibility.preflight_embedding_settings(cleared, self.candidate)
        inspect.assert_called_once()

    def test_runtime_rejects_settings_that_bypass_the_vector_baseline(self):
        with self.assertRaises(AIConnectionError) as raised:
            compatibility.active_embedding_profile(self.candidate)
        self.assertEqual(raised.exception.code, "embedding_profile_mismatch")

    def test_credential_rotation_does_not_inspect_stores_or_freeze_writes(self):
        candidate = copy.deepcopy(self.current)
        candidate["model_endpoints"][0]["auth"]["api_key"] = "rotated-synthetic"
        with patch.object(compatibility, "acquire_data_management_search_write_fence") as fence:
            with compatibility.embedding_settings_write_guard(self.current, candidate):
                pass
        fence.assert_not_called()
        self.assertEqual(candidate[EMBEDDING_VECTOR_PROFILE_KEY], self.profile.as_state())

    def test_equivalent_connection_reference_retains_legacy_vector_readability(self):
        candidate = copy.deepcopy(self.current)
        candidate[EMBEDDING_VECTOR_PROFILE_KEY]["legacy"] = True
        candidate["model_endpoints"][0]["id"] = "consolidated-connection"
        candidate[EMBEDDING_SELECTION_KEY]["endpoint_id"] = "consolidated-connection"
        resolved = resolve_embedding_profile(candidate)
        self.assertEqual(resolved.profile_id, self.profile.profile_id)
        self.assertTrue(resolved.legacy)

    def test_activation_holds_and_renews_fence_through_settings_commit(self):
        events = []
        fence = {"token": "test"}
        with (
            patch.object(compatibility, "_runtime_containers", return_value=(None, "jobs", self.facts)),
            patch.object(compatibility, "acquire_data_management_search_write_fence", side_effect=lambda *args, **kwargs: events.append("acquire") or fence),
            patch.object(compatibility, "inspect_empty_embedding_stores", side_effect=lambda *args: events.append("inspect") or {}),
            patch.object(compatibility, "renew_data_management_search_write_fence", side_effect=lambda *args: events.append("renew")),
            patch.object(compatibility, "publish_data_management_embedding_profile", side_effect=lambda container, token, profile_id: events.append("pending" if profile_id.startswith("pending:") else "publish")),
            patch.object(compatibility, "release_data_management_search_write_fence", side_effect=lambda *args: events.append("release") or True),
        ):
            with compatibility.embedding_settings_write_guard(self.current, self.candidate):
                events.append("commit")
                self.assertEqual(self.candidate[EMBEDDING_VECTOR_PROFILE_KEY], {**self.next_profile.as_state(), "indexes": {}})
        self.assertEqual(events, ["acquire", "inspect", "renew", "pending", "commit", "publish", "release"])

    def test_stale_inflight_vector_cannot_write_after_model_activation(self):
        stale = runtime.EmbeddingVector([1, 2, 3], self.profile)
        activated = copy.deepcopy(self.candidate)
        activated[EMBEDDING_VECTOR_PROFILE_KEY] = self.next_profile.as_state()
        with self.assertRaises(AIConnectionError) as raised:
            compatibility.assert_embedding_vector_current(stale, activated)
        self.assertEqual(raised.exception.code, "embedding_profile_changed")

    def test_new_vectors_require_provenance_field_but_never_send_it_before_schema_update(self):
        client = types.SimpleNamespace(index_name="simplechat-user-index")
        documents = [{"id": "chunk", "embedding": runtime.EmbeddingVector([1, 2, 3], self.profile)}]
        with patch.object(compatibility, "get_embedding_search_index_client") as schema_client:
            with self.assertRaises(AIConnectionError) as raised:
                compatibility.prepare_embedding_search_documents(client, documents, self.current)
            self.assertEqual(raised.exception.code, "embedding_schema_update_required")
            self.assertNotIn("embedding_profile_id", documents[0])
            self.current[EMBEDDING_VECTOR_PROFILE_KEY]["indexes"] = {
                "simplechat-user-index": {"exists": True, "dimensions": 3, "provenance": True},
            }
            compatibility.prepare_embedding_search_documents(client, documents, self.current)
        schema_client.assert_not_called()
        self.assertEqual(documents[0]["embedding_profile_id"], self.profile.profile_id)

    def test_dynamic_creation_updates_both_dimensions_without_mutating_shipped_definition(self):
        definition = {"fields": [{"name": "embedding", "dimensions": 1536}, {"name": "video_ocr_embedding", "dimensions": 1536}]}
        result = compatibility.build_embedding_index_schema(definition, self.current)
        self.assertEqual([field["dimensions"] for field in result["fields"]], [3, 3])
        self.assertEqual(definition["fields"][0]["dimensions"], 1536)

    def test_fact_persistence_checks_profile_inside_write_slot(self):
        events = []
        vector = runtime.EmbeddingVector([1, 2, 3], self.profile)
        with (
            patch.object(compatibility, "_runtime_containers", return_value=(None, "jobs", self.facts)),
            patch.object(compatibility, "hold_data_management_search_write_slot", return_value=nullcontext()),
            patch.object(compatibility, "active_embedding_profile", return_value=self.next_profile),
        ):
            with self.assertRaises(AIConnectionError):
                compatibility.persist_fact_with_embedding(self.facts, {"value_embedding": vector}, vector)
        self.facts.upsert_item.assert_not_called()

    def test_cross_worker_stale_settings_cannot_bypass_the_cas_profile_fence(self):
        fence = gates.acquire_data_management_search_write_fence(self.gate, "activation", 600)
        gates.publish_data_management_embedding_profile(self.gate, fence, self.next_profile.profile_id)
        gates.release_data_management_search_write_fence(self.gate, fence)
        stale_vector = runtime.EmbeddingVector([1, 2, 3], self.profile)
        with (
            patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)),
            patch.object(compatibility, "read_embedding_settings", return_value=self.current),
            self.assertRaises(gates.DataManagementEmbeddingProfileChangedError),
        ):
            compatibility.persist_fact_with_embedding(self.facts, {"value_embedding": stale_vector}, stale_vector)
        self.facts.upsert_item.assert_not_called()

    def test_write_intent_blocks_switch_even_if_session_consistent_counts_are_stale(self):
        vector = runtime.EmbeddingVector([1, 2, 3], self.profile)
        with (
            patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)),
            patch.object(compatibility, "read_embedding_settings", return_value=self.current),
            patch.object(compatibility, "inspect_empty_embedding_stores", return_value={}) as inspect,
        ):
            compatibility.persist_fact_with_embedding(self.facts, {"value_embedding": vector}, vector)
            with self.assertRaises(AIConnectionError) as raised:
                with compatibility.embedding_settings_write_guard(self.current, self.candidate):
                    self.fail("Settings must not commit while write history is present.")
        self.assertEqual(raised.exception.code, "embedding_rebuild_required")
        inspect.assert_not_called()
        self.assertTrue(self.gate.items[gates.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID]["embedding_vectors_written"])

    def test_ambiguous_commit_leaves_a_closed_vector_profile_until_explicit_retry(self):
        with (
            patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)),
            patch.object(compatibility, "inspect_empty_embedding_stores", return_value={}),
        ):
            with self.assertRaises(RuntimeError):
                with compatibility.embedding_settings_write_guard(self.current, self.candidate):
                    raise RuntimeError("Uncertain settings commit")
            gate = self.gate.items[gates.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID]
            self.assertTrue(gate["embedding_profile_id"].startswith("pending:"))
            with self.assertRaises(gates.DataManagementEmbeddingProfileChangedError):
                with gates.hold_data_management_search_write_slot(self.gate, embedding_profile_id=self.profile.profile_id):
                    self.fail("Old vectors must not be allowed after an uncertain commit.")
            restored = copy.deepcopy(self.current)
            with compatibility.embedding_settings_write_guard(self.current, restored, force_check=True):
                pass
        self.assertEqual(self.gate.items[gates.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID]["embedding_profile_id"], self.profile.profile_id)

    def test_legacy_queries_and_writes_do_not_require_index_management_permissions(self):
        settings = copy.deepcopy(self.current)
        settings[EMBEDDING_VECTOR_PROFILE_KEY]["legacy"] = True
        profile = resolve_embedding_profile(settings)
        client = types.SimpleNamespace(_index_name="simplechat-user-index")
        documents = [{"id": "chunk", "embedding": runtime.EmbeddingVector([1, 2, 3], profile)}]
        with patch.object(compatibility, "get_embedding_search_index_client", side_effect=AssertionError("Schema management is not permitted")):
            self.assertEqual(compatibility.embedding_search_filter(client, profile, settings), "")
            compatibility.prepare_embedding_search_documents(client, documents, settings)
        self.assertNotIn("embedding_profile_id", documents[0])

    def test_schema_maintenance_does_not_claim_vector_writes(self):
        with patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)):
            with compatibility.embedding_index_maintenance(self.current):
                pass
        state = self.gate.items[gates.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID]
        self.assertEqual(state["embedding_profile_id"], self.profile.profile_id)
        self.assertFalse(state.get("embedding_vectors_written"))

    def test_admin_schema_observation_is_persisted_with_settings_cas(self):
        container = FakeCosmos()
        container.document = {**copy.deepcopy(self.current), "id": "app_settings", "_etag": "1"}
        container.replace_item = Mock(wraps=container.replace_item)
        cache = FakeRedis()
        store = AppSettingsStore(container, cache, redis_required=True)
        with patch.object(compatibility, "_get_embedding_settings_store", return_value=store):
            compatibility.record_embedding_index_schema(index_schema(), self.current)
        write = container.replace_item.call_args.kwargs
        self.assertEqual(write["etag"], "1")
        self.assertEqual(
            write["body"][EMBEDDING_VECTOR_PROFILE_KEY]["indexes"]["simplechat-user-index"],
            {"exists": True, "dimensions": 3, "provenance": True},
        )
        self.assertEqual(container.document, json.loads(cache.raw)["document"])
        self.assertEqual(1, container.document[SETTINGS_REVISION_FIELD])

    def test_identical_schema_observation_does_not_write_or_invalidate_form(self):
        container = FakeCosmos()
        container.document = {**copy.deepcopy(self.current), "id": "app_settings", "_etag": "1"}
        store = AppSettingsStore(container)
        with patch.object(compatibility, "_get_embedding_settings_store", return_value=store):
            compatibility.record_embedding_index_schema(index_schema(), self.current)
            before = store.read(use_cosmos=True)
            writes = container.writes
            revision = compatibility.record_embedding_index_schema(
                index_schema(), before, expected_etag=before["_etag"],
            )
        self.assertEqual(container.writes, writes)
        self.assertEqual(revision, before["_etag"])
        stored = store.write(
            lambda current: {**current, "app_title": "Still editable"},
            expected_etag=before["_etag"],
        )
        self.assertEqual(stored["app_title"], "Still editable")

    def test_schema_observation_returns_only_its_own_conditional_revision(self):
        container = FakeCosmos()
        container.document = {**copy.deepcopy(self.current), "id": "app_settings", "_etag": "1"}
        store = AppSettingsStore(container)
        with patch.object(compatibility, "_get_embedding_settings_store", return_value=store):
            revision = compatibility.record_embedding_index_schema(
                index_schema(), self.current, expected_etag="1",
            )
        self.assertEqual(revision, container.document["_etag"])
        self.assertNotEqual(revision, "1")

    def test_schema_observation_does_not_fast_forward_a_stale_form(self):
        container = FakeCosmos()
        container.document = {**copy.deepcopy(self.current), "id": "app_settings", "_etag": "1"}
        store = AppSettingsStore(container)
        store.write(lambda current: {**current, "app_title": "Another admin"})
        writes = container.writes
        with patch.object(compatibility, "_get_embedding_settings_store", return_value=store):
            with self.assertRaises(AIConnectionError) as raised:
                compatibility.record_embedding_index_schema(
                    index_schema(), self.current, expected_etag="1",
                )
        self.assertEqual(raised.exception.code, "settings_conflict")
        self.assertEqual(container.writes, writes)
        self.assertEqual(container.document["app_title"], "Another admin")

    def test_concurrent_edit_during_schema_observation_keeps_form_stale(self):
        container = FakeCosmos()
        container.document = {**copy.deepcopy(self.current), "id": "app_settings", "_etag": "1"}
        store = AppSettingsStore(container)
        container.before_replace = lambda: store.write(
            lambda current: {**current, "app_title": "Concurrent edit"},
        )
        with patch.object(compatibility, "_get_embedding_settings_store", return_value=store):
            with self.assertRaises(AIConnectionError) as raised:
                compatibility.record_embedding_index_schema(
                    index_schema(), self.current, expected_etag="1",
                )
        self.assertEqual(raised.exception.code, "settings_conflict")
        self.assertEqual(container.writes, 1)
        self.assertEqual(container.document["app_title"], "Concurrent edit")

    def test_schema_observation_retries_without_losing_other_index_metadata(self):
        container = FakeCosmos()
        container.document = {**copy.deepcopy(self.current), "id": "app_settings", "_etag": "1"}
        store = AppSettingsStore(container)
        newer_baseline = copy.deepcopy(self.current[EMBEDDING_VECTOR_PROFILE_KEY])
        newer_baseline["indexes"] = {"another-index": {"exists": True, "dimensions": 3, "provenance": True}}
        container.before_replace = lambda: store.write(lambda current: {
            **current, EMBEDDING_VECTOR_PROFILE_KEY: newer_baseline, "app_title": "Concurrent edit",
        })
        with patch.object(compatibility, "_get_embedding_settings_store", return_value=store):
            compatibility.record_embedding_index_schema(index_schema(), self.current)
        self.assertEqual("Concurrent edit", container.document["app_title"])
        self.assertEqual(
            {"another-index", "simplechat-user-index"},
            set(container.document[EMBEDDING_VECTOR_PROFILE_KEY]["indexes"]),
        )
        self.assertEqual(2, container.document[SETTINGS_REVISION_FIELD])

    def test_schema_observation_cannot_follow_a_concurrent_model_switch(self):
        container = FakeCosmos()
        container.document = {**copy.deepcopy(self.current), "id": "app_settings", "_etag": "1"}
        store = AppSettingsStore(container)
        container.before_replace = lambda: store.write(lambda current: {
            **current, **copy.deepcopy(self.candidate),
            EMBEDDING_VECTOR_PROFILE_KEY: self.next_profile.as_state(),
        })
        with (
            patch.object(compatibility, "_get_embedding_settings_store", return_value=store),
            self.assertRaises(AIConnectionError) as raised,
        ):
            compatibility.record_embedding_index_schema(index_schema(), self.current)
        self.assertEqual("embedding_profile_changed", raised.exception.code)
        self.assertEqual(1, container.writes)
        self.assertEqual(self.next_profile.profile_id, container.document[EMBEDDING_VECTOR_PROFILE_KEY]["id"])

    def test_embedding_settings_use_authoritative_shared_store_reads(self):
        store = Mock()
        store.read.return_value = copy.deepcopy(self.current)
        with (
            patch.object(compatibility, "_get_embedding_settings_store", return_value=store),
            patch.object(compatibility, "_runtime_containers", side_effect=AssertionError("No direct settings read")),
        ):
            self.assertEqual(self.current, compatibility.read_embedding_settings())
        store.read.assert_called_once_with(use_cosmos=True)

    def test_query_profile_check_rejects_stale_settings_without_marking_vector_writes(self):
        fence = gates.acquire_data_management_search_write_fence(self.gate, "activation", 600)
        gates.publish_data_management_embedding_profile(self.gate, fence, self.next_profile.profile_id)
        gates.release_data_management_search_write_fence(self.gate, fence)
        with patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)):
            with self.assertRaises(gates.DataManagementEmbeddingProfileChangedError):
                with compatibility.embedding_query_slot(self.profile.profile_id):
                    self.fail("Stale retrieval must not be evaluated against new-model vectors.")
            with compatibility.embedding_query_slot(self.next_profile.profile_id):
                pass
        self.assertFalse(self.gate.items[gates.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID].get("embedding_vectors_written"))

    def test_clear_invalidates_stale_readers_but_preserves_same_space_reactivation(self):
        with gates.hold_data_management_search_write_slot(self.gate, embedding_profile_id=self.profile.profile_id):
            pass
        cleared = copy.deepcopy(self.current)
        cleared[EMBEDDING_SELECTION_KEY] = {"endpoint_id": "", "model_id": "", "provider": ""}
        with patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)):
            with compatibility.embedding_settings_write_guard(self.current, cleared, force_check=True):
                pass
            state = self.gate.items[gates.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID]
            self.assertEqual(state["embedding_profile_id"], f"inactive:{self.profile.profile_id}")
            self.assertTrue(state["embedding_vectors_written"])
            with self.assertRaises(gates.DataManagementEmbeddingProfileChangedError):
                with compatibility.embedding_query_slot(self.profile.profile_id):
                    self.fail("A stale cached default must not survive an explicit clear.")
            restored = copy.deepcopy(self.current)
            with compatibility.embedding_settings_write_guard(cleared, restored, force_check=True):
                pass
        state = self.gate.items[gates.DATA_MANAGEMENT_SEARCH_WRITE_GATE_ID]
        self.assertEqual(state["embedding_profile_id"], self.profile.profile_id)
        self.assertTrue(state["embedding_vectors_written"])

    def test_search_pages_are_bounded_and_use_profile_coordination(self):
        client = Mock()
        client.search.return_value.by_page.return_value = iter([[{"id": "one"}, {"id": "two"}]])
        with patch.object(compatibility, "_runtime_containers", return_value=(None, self.gate, self.facts)):
            result = compatibility.search_with_embedding_profile(
                client, self.profile, search_text="question", top=2,
            )
        self.assertEqual(result, [{"id": "one"}, {"id": "two"}])
        self.assertEqual(client.search.call_args.kwargs["retry_total"], 0)
        self.assertEqual(client.search.call_args.kwargs["read_timeout"], 30)


if __name__ == "__main__":
    unittest.main()
