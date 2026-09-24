# test_ai_connection_embedding_consumers.py
"""
Functional coverage for embedding consumer wiring and persistence boundaries.
Version: 0.261.163
Implemented in: 0.261.106

Load the actual consumer functions/classes against isolated collaborators to
exercise action routing, fact provenance, and fenced document vector writes.
"""

import ast
import copy
import hashlib
import sys
import types
import unittest
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

from test_ai_connection_embedding_runtime import custom_settings, runtime
from functions_ai_connections import AIConnectionError
from functions_embedding_profile import resolve_embedding_profile


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


def load_nodes(filename, names, namespace):
    source = ast.parse((APP_ROOT / filename).read_text(encoding="utf-8-sig"))
    nodes = [
        copy.deepcopy(node) for node in source.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
    ]
    if len(nodes) != len(names):
        raise AssertionError(f"Expected consumer nodes were not found in {filename}.")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class EmbeddingConsumerTests(unittest.TestCase):
    def setUp(self):
        self.profile = resolve_embedding_profile(custom_settings())
        self.vector = runtime.EmbeddingVector([1, 2, 3], self.profile)

    def plugin(self):
        namespace = {
            "Dict": Dict, "Any": Any, "List": List, "BasePlugin": object,
            "generate_embedding": Mock(return_value=(self.vector, None)),
            "plugin_function_logger": lambda *args, **kwargs: lambda func: func,
            "kernel_function": lambda *args, **kwargs: lambda func: func,
            "requests": Mock(),
        }
        return load_nodes("semantic_kernel_plugins\\embedding_model_plugin.py", {"EmbeddingModelPlugin"}, namespace)

    def test_default_action_uses_shared_runtime_without_requiring_a_legacy_key(self):
        namespace = self.plugin()
        plugin = namespace["EmbeddingModelPlugin"]()
        self.assertEqual(plugin.embed("sample"), self.vector)
        namespace["generate_embedding"].assert_called_once_with("sample", purpose="text")
        namespace["requests"].post.assert_not_called()

    def test_explicit_action_manifest_is_not_redirected_to_global_default(self):
        namespace = self.plugin()
        namespace["requests"].post.return_value.json.return_value = {"data": [{"embedding": [3, 2, 1]}]}
        plugin = namespace["EmbeddingModelPlugin"]({
            "endpoint": "https://action.example.test", "deployment": "separate",
            "api_version": "2024-06-01", "auth": {"key": "synthetic-action-key"},
        })
        self.assertEqual(plugin.embed("sample"), [3, 2, 1])
        namespace["generate_embedding"].assert_not_called()
        self.assertEqual(
            namespace["requests"].post.call_args.args[0],
            "https://action.example.test/openai/deployments/separate/embeddings?api-version=2024-06-01",
        )

    def test_action_loader_checks_the_shared_binding_not_legacy_endpoint_key_fields(self):
        namespace = {
            "Kernel": object, "resolve_embedding_profile": resolve_embedding_profile,
            "AIConnectionError": AIConnectionError, "log_event": Mock(),
            "EmbeddingModelPlugin": Mock(),
        }
        load_nodes("semantic_kernel_loader.py", {"load_embedding_model_plugin"}, namespace)
        kernel = Mock()
        namespace["load_embedding_model_plugin"](kernel, custom_settings())
        kernel.add_plugin.assert_called_once()
        empty_kernel = Mock()
        namespace["load_embedding_model_plugin"](empty_kernel, {})
        empty_kernel.add_plugin.assert_not_called()
        namespace["log_event"].assert_called_once()

    def test_new_fact_vectors_keep_provenance_when_provider_omits_usage(self):
        container = Mock()
        persist = Mock()
        namespace = {
            "uuid": uuid, "datetime": datetime, "timezone": timezone,
            "cosmos_agent_facts_container": container, "exceptions": types.SimpleNamespace(),
            "generate_embedding": Mock(return_value=(self.vector, None)), "log_event": Mock(),
            "persist_fact_with_embedding": persist,
            "MEMORY_TYPE_FACT": "fact", "MEMORY_TYPE_INSTRUCTION": "instruction",
            "MEMORY_TYPE_LEGACY_DESCRIBER": "describer",
            "VALID_MEMORY_TYPES": {"fact", "instruction", "describer"}, "UNSET": object(),
        }
        load_nodes("semantic_kernel_fact_memory_store.py", {"FactMemoryStore"}, namespace)
        store = namespace["FactMemoryStore"](container)
        fact = store.set_fact("user", "authorized-user", "a fact")
        self.assertEqual(fact["embedding_profile_id"], self.profile.profile_id)
        self.assertIsNone(fact["embedding_model"])
        persist.assert_called_once()
        container.upsert_item.assert_not_called()
        instruction = store.set_fact("user", "authorized-user", "be concise", memory_type="instruction")
        self.assertIsNone(instruction["value_embedding"])
        container.upsert_item.assert_called_once()
        namespace["generate_embedding"].side_effect = runtime.EmbeddingInferenceError(
            "Embedding authentication failed.", "embedding_authentication_failed",
        )
        unavailable = store.set_fact("user", "authorized-user", "retain this fact text")
        self.assertIsNone(unavailable["value_embedding"])
        self.assertEqual(container.upsert_item.call_args.args[0]["value"], "retain this fact text")

    def test_vector_preparation_is_inside_fence_and_precedes_search_mutation(self):
        events = []

        @contextmanager
        def slot(container, **options):
            self.assertEqual(options["embedding_profile_id"], self.profile.profile_id)
            events.append("slot")
            yield
            events.append("release")

        prepare = Mock(side_effect=lambda *args: events.append("profile"))
        client = Mock()
        client.upload_documents.side_effect = lambda **kwargs: events.append("write") or [{"succeeded": True}]
        namespace = {
            "hold_data_management_search_write_slot": slot,
            "cosmos_data_management_jobs_container": object(),
            "prepare_embedding_search_documents": prepare,
            # A non-group write holds no projection fence: `nullcontext(None)` stands in for it.
            "nullcontext": nullcontext,
        }
        load_nodes("functions_documents.py", {"_execute_document_search_write", "_search_indexing_results_succeeded"}, namespace)
        namespace["_execute_document_search_write"](client, "upload_documents", documents=[{"id": "chunk", "embedding": self.vector}])
        self.assertEqual(events, ["slot", "profile", "write", "release"])
        prepare.side_effect = AIConnectionError("Profile changed")
        client.reset_mock()
        with self.assertRaises(AIConnectionError):
            namespace["_execute_document_search_write"](client, "upload_documents", documents=[{"id": "chunk", "embedding": self.vector}])
        client.upload_documents.assert_not_called()

    def test_visibility_updates_do_not_rewrite_vectors_or_require_an_embedding_default(self):
        client = Mock()
        client.search.return_value = [{"id": "chunk", "embedding": [1, 2, 3], "chunk_text": "retained"}]
        execute = Mock()
        namespace = {
            "_get_search_client": Mock(return_value=client),
            "_build_archived_scope_value": lambda value: f"archived:{value}",
            "_execute_document_search_write": execute,
        }
        load_nodes("functions_documents.py", {"set_document_chunk_visibility"}, namespace)
        count = namespace["set_document_chunk_visibility"]({"id": "document", "user_id": "owner"}, active=False)
        self.assertEqual(count, 1)
        self.assertEqual(execute.call_args.args[1], "merge_documents")
        self.assertEqual(execute.call_args.kwargs["documents"], [{
            "id": "chunk", "user_id": "archived:owner", "shared_user_ids": [],
        }])

    def test_retrieval_cache_keys_are_isolated_by_embedding_profile_for_every_scope(self):
        namespace = {
            "hashlib": hashlib, "List": List, "Optional": Optional,
            "get_personal_document_fingerprint": lambda scope: "personal-v1",
            "get_group_document_fingerprint": lambda scope: "group-v1",
            "get_public_workspace_document_fingerprint": lambda scope: "public-v1",
            "_debug_print": Mock(),
            "logger": Mock(),
        }
        load_nodes("utils_cache.py", {"generate_search_cache_key", "_normalize_cache_id_list"}, namespace)
        make_key = namespace["generate_search_cache_key"]
        for scope in ("personal", "group", "public", "all"):
            args = {
                "query": "question", "user_id": "user", "doc_scope": scope,
                "active_group_ids": ["group"], "active_public_workspace_id": "public",
            }
            with self.subTest(scope=scope):
                original = make_key(**args)
                first = make_key(**args, embedding_profile_id="space-one")
                second = make_key(**args, embedding_profile_id="space-two")
                self.assertNotEqual(original, first)
                self.assertNotEqual(first, second)

    def test_retrieval_checks_profile_before_cache_and_labels_query_embeddings(self):
        source = ast.parse((APP_ROOT / "functions_search.py").read_text(encoding="utf-8"))
        search = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "hybrid_search")
        calls = [node for node in ast.walk(search) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        active = next(node for node in calls if node.func.id == "active_embedding_profile")
        cached = next(node for node in calls if node.func.id == "get_cached_search_results")
        self.assertLess(active.lineno, cached.lineno)
        embedding = next(node for node in calls if node.func.id == "generate_embedding")
        purpose = next(keyword.value for keyword in embedding.keywords if keyword.arg == "purpose")
        self.assertEqual(purpose.value, "query")


if __name__ == "__main__":
    unittest.main()
