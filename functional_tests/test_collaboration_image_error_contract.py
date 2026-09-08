# test_collaboration_image_error_contract.py
"""
Functional test for the shared image editor's error/status contract.
Version: 0.261.102
Implemented in: 0.261.102

Execute the production image-operation exception handler with real error types
and response mapping. Existing route-policy tests cover its authorization guards.
"""

import ast
import copy
import logging
import sys
import unittest
from pathlib import Path

from flask import jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ai_connection_image_runtime import (
    APP_ROOT,
    ImageRuntimeTestCase,
    connections,
    generation,
    image_edit,
    image_route,
)


class CollaborationImageErrorTests(ImageRuntimeTestCase):
    def test_shared_editor_retains_rate_limit_configuration_and_refusal_statuses(self):
        source = APP_ROOT / "route_backend_collaboration.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        route = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "add_collaboration_image_revision_api"
        )
        handler = next(
            node for node in ast.walk(route)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Tuple)
            and {item.id for item in node.type.elts if isinstance(item, ast.Name)}
            == {"ImageGenerationError", "AIConnectionError"}
        )
        function = ast.parse("def exercise():\n    pass\n").body[0]
        function.body = [
            ast.Try(
                body=[ast.Raise(exc=ast.Name(id="failure", ctx=ast.Load()), cause=None)],
                handlers=[copy.deepcopy(handler)], orelse=[], finalbody=[],
            )
        ]
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        cases = (
            (image_edit.ImageEditError("Rate limited.", "image_rate_limited", 429), 429),
            (connections.AIConnectionError("Choose an image model.", "model_configuration_unavailable"), 503),
            (image_route.ImageGenerationError(
                "Image request blocked.", "image_content_blocked", 400,
                {"provider_message": "private-provider-detail"},
            ), 400),
        )
        for failure, expected_status in cases:
            with self.subTest(code=failure.code):
                namespace = {
                    "failure": failure,
                    "ImageGenerationError": image_route.ImageGenerationError,
                    "AIConnectionError": connections.AIConnectionError,
                    "image_generation_error_response": generation.image_generation_error_response,
                    "log_event": lambda *_args, **_kwargs: None,
                    "logging": logging,
                    "message_id": "shared-image",
                    "jsonify": jsonify,
                }
                exec(compile(module, str(source), "exec"), namespace)
                with self.app.test_request_context():
                    response, status = namespace["exercise"]()
                payload = response.get_json()
                self.assertEqual(expected_status, status)
                self.assertEqual(failure.public_message, payload["error"])
                self.assertEqual(failure.code, payload["error_code"])
                self.assertEqual(expected_status == 429, payload.get("rate_limited", False))
                self.assertNotIn("private-provider-detail", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
