# test_onenote_upload_dispatch.py
"""
Functional tests for shared OneNote workspace upload dispatch.
Version: 0.261.045
Implemented in: 0.261.045

Validates shared allowlists, dispatch for every workspace scope, safe error
status, and temporary-file cleanup without connecting to Azure services.
"""

import ast
import contextlib
import io
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_onenote_workspace_ingestion import APP_ROOT, chunk_tests, onenote


def config_namespace():
    path = APP_ROOT / "config.py"
    namespace = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Set):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("EXTENSIONS"):
                    namespace[target.id] = ast.literal_eval(node.value)
    chunk_tests.load_functions(
        path, ["get_allowed_extensions", "get_allowed_extension_categories"], namespace
    )
    namespace["ALLOWED_EXTENSIONS"] = namespace["get_allowed_extensions"](True, True)
    chunk_tests.load_functions(APP_ROOT / "functions_documents.py", ["allowed_file"], namespace)
    return namespace


class OneNoteUploadDispatchTests(unittest.TestCase):
    def test_formats_are_allowed_without_changing_document_intelligence_types(self):
        namespace = config_namespace()
        for filename in ("fixture.one", "fixture.ONE", "fixture.onepkg", "fixture.ONEPKG"):
            allowed = namespace["allowed_file"](filename)
            self.assertTrue(allowed)
        self.assertTrue({"one", "onepkg"}.isdisjoint(namespace["DOCUMENT_EXTENSIONS"]))
        rejected = namespace["allowed_file"]("fixture.onetoc2")
        self.assertFalse(rejected)

    def test_direct_chat_attachment_allowlist_does_not_expand(self):
        namespace = config_namespace()
        path = APP_ROOT / "route_frontend_chats.py"
        node = next(
            node for node in ast.parse(path.read_text(encoding="utf-8")).body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "CHAT_WORKSPACE_UPLOAD_EXTENSIONS" for target in node.targets)
        )
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
        self.assertTrue({"one", "onepkg"}.isdisjoint(namespace["CHAT_WORKSPACE_UPLOAD_EXTENSIONS"]))

    def run_dispatch(self, suffix, scope, failure=None):
        namespace = config_namespace()
        metadata = {"id": "document-1", "file_name": f"fixture{suffix}", "author": "Fixture"}
        processor = Mock(side_effect=failure, return_value=(3, 21, "fixture-embedding"))
        container = types.SimpleNamespace(
            read_item=lambda **kwargs: dict(metadata),
            upsert_item=lambda item: None,
        )
        namespace.update({
            "os": os,
            "logging": logging,
            "get_settings": lambda: {"max_file_size_mb": 50},
            "update_document": lambda **kwargs: metadata.update(kwargs),
            "get_document_metadata": lambda **kwargs: dict(metadata),
            "process_onenote": processor,
            "_run_final_metadata_extraction": lambda *args, **kwargs: "disabled",
            "sync_chat_upload_workspace_attachment_status": lambda value: None,
            "cosmos_user_documents_container": container,
            "cosmos_group_documents_container": container,
            "cosmos_public_documents_container": container,
            "log_event": lambda *args, **kwargs: None,
        })
        chunk_tests.load_functions(
            APP_ROOT / "functions_documents.py",
            ["process_document_upload_background", "_resolve_processing_complete_status"],
            namespace,
        )
        activity = types.ModuleType("functions_activity_logging")
        activity.log_document_creation_transaction = lambda **kwargs: None
        activity.log_token_usage = lambda **kwargs: None
        notifications = types.ModuleType("functions_notifications")
        notifications.create_notification = lambda **kwargs: None
        notifications.create_group_notification = lambda **kwargs: None
        notifications.create_public_workspace_notification = lambda **kwargs: None
        groups = types.ModuleType("functions_group")
        groups.find_group_by_id = lambda group_id: {"id": group_id, "name": "Fixture"}

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / f"fixture{suffix}"
            source.write_bytes(b"native input is covered by separate extractor tests")
            with patch.dict(sys.modules, {
                "functions_activity_logging": activity,
                "functions_notifications": notifications,
                "functions_group": groups,
            }):
                with contextlib.redirect_stdout(io.StringIO()):
                    namespace["process_document_upload_background"](
                        document_id="document-1", user_id="user-1",
                        temp_file_path=str(source), original_filename=source.name, **scope,
                    )
            source_exists = source.exists()
        return processor, metadata, source_exists

    def test_all_workspace_scopes_dispatch_both_formats_and_clean_up(self):
        for suffix in (".one", ".ONEPKG"):
            for scope in ({}, {"group_id": "group-1"}, {"public_workspace_id": "public-1"}):
                with self.subTest(suffix=suffix, scope=scope):
                    processor, metadata, source_exists = self.run_dispatch(suffix, scope)
                    self.assertEqual(processor.call_count, 1)
                    self.assertEqual(processor.call_args.kwargs["user_id"], "user-1")
                    self.assertEqual(processor.call_args.kwargs["document_id"], "document-1")
                    self.assertFalse(processor.call_args.kwargs["auto_extract_metadata"])
                    for key, value in scope.items():
                        self.assertEqual(processor.call_args.kwargs[key], value)
                    self.assertNotIn("file_ext", processor.call_args.kwargs)
                    self.assertEqual(metadata["number_of_pages"], 3)
                    self.assertEqual(metadata["embedding_tokens"], 21)
                    self.assertEqual(metadata["percentage_complete"], 100)
                    self.assertIn("OneNote typed text only", metadata["status"])
                    self.assertFalse(source_exists)

    def test_native_failure_marks_error_and_cleans_up(self):
        failure = onenote.OneNoteExtractionError("incomplete_notebook")
        _, metadata, source_exists = self.run_dispatch(".onepkg", {}, failure)
        self.assertTrue(metadata["status"].startswith("Error:"))
        self.assertIn("complete OneNote notebook could not be read", metadata["status"])
        self.assertEqual(metadata["percentage_complete"], 0)
        self.assertFalse(source_exists)


if __name__ == "__main__":
    unittest.main()
