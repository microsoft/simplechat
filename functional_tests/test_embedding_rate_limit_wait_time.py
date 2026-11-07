# test_embedding_rate_limit_wait_time.py
"""
Functional test for embedding rate-limit wait times through the shared runtime.
Version: 0.261.106
Implemented in: 0.239.116; updated in 0.261.106

Exercise the real single/batch entrypoints and header parser without provider
requests, application initialization, or real retry waits.
"""

import ast
import email.utils
import random
import sys
import time
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from test_ai_connection_embedding_runtime import custom_settings, runtime
from functions_ai_connections import AIConnectionError
from functions_embedding_profile import resolve_embedding_profile


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


class FakeRateLimitError(Exception):
    def __init__(self, headers):
        super().__init__("rate limited")
        self.response = types.SimpleNamespace(headers=headers)


class EmbeddingRetryTests(unittest.TestCase):
    def setUp(self):
        self.settings = custom_settings()
        self.profile = resolve_embedding_profile(self.settings)
        names = {"_parse_retry_after_seconds", "_get_rate_limit_wait_time", "generate_embedding", "generate_embeddings_batch"}
        tree = ast.parse((APP_ROOT / "functions_content.py").read_text(encoding="utf-8"))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in nodes}, names)
        namespace = {
            "email": email, "random": random, "time": time,
            "AIConnectionError": AIConnectionError,
            "read_embedding_settings": lambda: self.settings,
            "active_embedding_profile": resolve_embedding_profile,
            "generate_embedding_batch": runtime.generate_embedding_batch,
            "embedding_query_slot": lambda _: nullcontext(),
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "functions_content.py", "exec"), namespace)
        self.functions = namespace

    def response(self, count):
        payload = {
            "data": [{"index": index, "embedding": [0.1, 0.2, 0.3]} for index in range(count)],
            "usage": {"prompt_tokens": 20, "total_tokens": 20},
        }
        return types.SimpleNamespace(http_response=types.SimpleNamespace(json=lambda: payload))

    def invoke(self, name, inputs, header):
        endpoint = Mock()
        endpoint.embeddings.with_raw_response.create.side_effect = [
            FakeRateLimitError(header), self.response(1 if isinstance(inputs, str) else len(inputs)),
        ]
        endpoint.__enter__ = Mock(return_value=endpoint)
        endpoint.__exit__ = Mock(return_value=False)
        with (
            patch.object(runtime, "create_capability_client", return_value=endpoint),
            patch.object(runtime, "RateLimitError", FakeRateLimitError),
            patch.object(runtime.time, "sleep") as sleep,
        ):
            result = self.functions[name](inputs)
        return result, sleep

    def test_parse_retry_after_ms_and_date_headers(self):
        parse = self.functions["_parse_retry_after_seconds"]
        self.assertEqual(parse({"retry-after-ms": "4500"}), 4.5)
        self.assertEqual(parse({"x-ms-retry-after-ms": "3000"}), 3)
        value = parse({"retry-after": email.utils.formatdate(time.time() + 5, usegmt=True)})
        self.assertGreater(value, 0)
        self.assertLessEqual(value, 5.5)
        self.assertIsNone(parse({"retry-after": "invalid"}))

    def test_generate_embedding_uses_retry_after_wait_time(self):
        (vector, usage), sleep = self.invoke("generate_embedding", "retry text", {"retry-after-ms": "4500"})
        self.assertEqual(vector, [0.1, 0.2, 0.3])
        self.assertEqual(usage["model_deployment_name"], "embed-prod")
        sleep.assert_called_once_with(4.5)

    def test_generate_embeddings_batch_uses_retry_after_wait_time(self):
        results, sleep = self.invoke("generate_embeddings_batch", ["first", "second"], {"retry-after": "3"})
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][1]["prompt_tokens"], 10)
        sleep.assert_called_once_with(3.0)

    def test_unreasonable_retry_headers_use_bounded_fallback(self):
        with patch.object(random, "uniform", return_value=1.0):
            delay = self.functions["_get_rate_limit_wait_time"](FakeRateLimitError({"retry-after": "9999"}), 2)
        self.assertEqual(delay, 2)


if __name__ == "__main__":
    unittest.main()
