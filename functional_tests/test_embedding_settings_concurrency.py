# test_embedding_settings_concurrency.py
"""
Functional coverage for conditional embedding-related settings persistence.
Version: 0.261.106
Implemented in: 0.261.106

Exercise the real settings writer with isolated Cosmos/cache seams, ensuring
concurrent updates and guard failures cannot be reported as successful saves.
"""

import ast
import copy
import logging
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch


class ConflictError(Exception):
    pass


class SafeConnectionError(ValueError):
    def __init__(self, message, code="invalid"):
        super().__init__(message)
        self.code = code


class EmbeddingSettingsConcurrencyTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_settings.py"
        node = next(
            node for node in ast.parse(source.read_text(encoding="utf-8")).body
            if isinstance(node, ast.FunctionDef) and node.name == "update_settings"
        )
        self.current = {
            "id": "app_settings", "_etag": "first",
            "embedding_vector_profile": {"id": "space-one", "dimensions": 1536},
            "app_title": "original",
        }
        self.store = Mock()
        self.store.read_item.side_effect = lambda **kwargs: copy.deepcopy(self.current)
        self.store.replace_item.side_effect = lambda **kwargs: {**kwargs["body"], "_etag": "saved"}
        self.refresh = Mock()
        self.guard = Mock(side_effect=lambda current, candidate, **kwargs: nullcontext())
        self.guard_module = types.ModuleType("functions_embedding_compatibility")
        self.guard_module.embedding_settings_write_guard = self.guard
        self.namespace = {
            "copy": copy, "logging": logging, "cosmos_settings_container": self.store,
            "CosmosAccessConditionFailedError": ConflictError,
            "AIConnectionError": SafeConnectionError,
            "EMBEDDING_SELECTION_KEY": "embedding_model_selection",
            "MatchConditions": types.SimpleNamespace(IfNotModified="if-not-modified"),
            "_refresh_app_settings_cache_after_write": self.refresh,
            "log_event": Mock(), "get_settings": Mock(),
            "coerce_multi_model_endpoint_enablement": lambda old, new: bool(old or new),
            "is_tabular_processing_enabled": lambda _: False,
        }
        for name in (
            "normalize_group_workflow_assignment_settings", "normalize_agents_page_promoted_popular_settings",
            "normalize_document_access_index_required_settings", "normalize_inbound_mcp_settings",
            "normalize_public_workspace_display_settings", "normalize_key_vault_reminder_settings",
            "normalize_model_endpoint_identity_header_settings",
        ):
            self.namespace[name] = lambda _: None
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), self.namespace)

    def save(self, values):
        with patch.dict(sys.modules, {"functions_embedding_compatibility": self.guard_module}):
            return self.namespace["update_settings"](values)

    def test_save_reads_authoritative_settings_and_refreshes_the_committed_revision(self):
        self.assertTrue(self.save({"app_title": "updated"}))
        self.namespace["get_settings"].assert_not_called()
        self.assertEqual(self.store.replace_item.call_args.kwargs["etag"], "first")
        self.assertEqual(self.store.replace_item.call_args.kwargs["match_condition"], "if-not-modified")
        persisted = self.refresh.call_args.args[0]
        self.assertEqual(persisted["_etag"], "saved")
        self.assertEqual(persisted["embedding_vector_profile"], self.current["embedding_vector_profile"])

    def test_conflict_rereads_and_preserves_other_administrators_new_profile(self):
        original = copy.deepcopy(self.current)
        newer = {**original, "_etag": "second", "embedding_vector_profile": {"id": "space-two", "dimensions": 1024}}
        self.store.read_item.side_effect = [original, newer]
        self.store.replace_item.side_effect = [
            ConflictError(),
            {**newer, "app_title": "updated", "_etag": "third"},
        ]
        self.assertTrue(self.save({"app_title": "updated"}))
        self.assertEqual(self.guard.call_count, 2)
        replacement = self.store.replace_item.call_args.kwargs
        self.assertEqual(replacement["etag"], "second")
        self.assertEqual(replacement["body"]["embedding_vector_profile"]["id"], "space-two")

    def test_exhausted_conflicts_raise_a_safe_error_without_refreshing_cache(self):
        self.store.replace_item.side_effect = ConflictError()
        with self.assertRaises(SafeConnectionError) as raised:
            self.save({"app_title": "updated"})
        self.assertEqual(raised.exception.code, "settings_conflict")
        self.assertEqual(self.store.replace_item.call_count, 3)
        self.refresh.assert_not_called()

    def test_compatibility_failure_never_writes_settings(self):
        self.guard.side_effect = SafeConnectionError("Rebuild required", "embedding_rebuild_required")
        with self.assertRaises(SafeConnectionError):
            self.save({"embedding_model_selection": {"endpoint_id": "new", "model_id": "new"}})
        self.store.replace_item.assert_not_called()
        self.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
