# test_embedding_settings_concurrency.py
"""
Functional coverage for conditional embedding-related settings persistence.
Version: 0.261.122
Implemented in: 0.261.106

Exercise the real settings writer with isolated Cosmos/cache seams, ensuring
concurrent updates and guard failures cannot be reported as successful saves.
"""

import copy
import json
import sys
import types
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from azure.cosmos.exceptions import CosmosAccessConditionFailedError

from test_app_settings_store_consistency import FakeCosmos, FakeRedis, load_update_settings, store_module


class EmbeddingSettingsConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.current = {
            "id": "app_settings", "_etag": "1",
            "embedding_vector_profile": {"id": "space-one", "dimensions": 1536},
            "app_title": "original",
        }
        self.store = FakeCosmos()
        self.store.document = copy.deepcopy(self.current)
        self.store.replace_item = Mock(wraps=self.store.replace_item)
        self.cache = FakeRedis()
        self.writer = store_module.AppSettingsStore(self.store, self.cache, redis_required=True)
        self.update_settings = load_update_settings(self.writer)
        self.namespace = self.update_settings.__globals__
        self.namespace["get_settings"] = Mock()
        self.namespace["log_event"] = Mock()
        self.connection_error = self.namespace["AIConnectionError"]
        self.guard = Mock(side_effect=lambda current, candidate, **kwargs: nullcontext())
        self.guard_module = types.ModuleType("functions_embedding_compatibility")
        self.guard_module.embedding_settings_write_guard = self.guard

    def save(self, values):
        with patch.dict(sys.modules, {"functions_embedding_compatibility": self.guard_module}):
            return self.update_settings(values)

    def test_save_reads_authoritative_settings_and_refreshes_the_committed_revision(self):
        self.assertTrue(self.save({"app_title": "updated"}))
        self.namespace["get_settings"].assert_not_called()
        self.assertEqual(self.store.replace_item.call_args.kwargs["etag"], "1")
        persisted = json.loads(self.cache.raw)["document"]
        self.assertEqual(persisted, self.store.document)
        self.assertEqual(persisted[store_module.SETTINGS_REVISION_FIELD], 1)
        self.assertEqual(persisted["embedding_vector_profile"], self.current["embedding_vector_profile"])

    def test_conflict_rereads_and_preserves_other_administrators_new_profile(self):
        other = store_module.AppSettingsStore(self.store)
        self.store.before_replace = lambda: other.write(lambda current: {
            **current, "embedding_vector_profile": {"id": "space-two", "dimensions": 1024},
        })
        self.assertTrue(self.save({"app_title": "updated"}))
        self.assertEqual(self.guard.call_count, 2)
        replacement = self.store.replace_item.call_args.kwargs
        self.assertEqual(replacement["etag"], "2")
        self.assertEqual(replacement["body"]["embedding_vector_profile"]["id"], "space-two")

    def test_exhausted_conflicts_report_failure_without_publishing_cache(self):
        self.store.replace_item.side_effect = CosmosAccessConditionFailedError(status_code=412, message="Conflict")
        self.assertFalse(self.save({"app_title": "updated"}))
        self.assertEqual(self.store.replace_item.call_count, store_module.MAX_WRITE_ATTEMPTS)
        self.assertEqual(json.loads(self.cache.raw)["state"], "pending")
        self.assertEqual(self.store.writes, 0)
        self.namespace["log_event"].assert_called()

    def test_compatibility_failure_never_writes_settings(self):
        self.guard.side_effect = self.connection_error("Rebuild required", "embedding_rebuild_required")
        with self.assertRaises(self.connection_error):
            self.save({"embedding_model_selection": {"endpoint_id": "new", "model_id": "new"}})
        self.store.replace_item.assert_not_called()
        self.assertEqual(json.loads(self.cache.raw)["state"], "pending")


if __name__ == "__main__":
    unittest.main()
