# test_onenote_development_revert.py
"""
Functional regression for reverting the premature Development OneNote rollout.
Version: 0.261.046
Implemented in: 0.261.046

Checks upload rejection and cleanup, retained legacy formats, source
classification, and removal of native packaging after reverting PR #1525.
The isolated upload namespace avoids initializing Azure clients.
"""

import ast
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import Mock

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
NOTEBOOK_EXTENSIONS = {"one", "onepkg"}
LEGACY_EXTENSIONS = {
    "txt", "doc", "docm", "html", "md", "json", "xml", "yaml", "yml", "log",
    "pdf", "docx", "pptx", "ppt", "csv", "xlsx", "xls", "xlsm", "xsd",
    "vsdx", "msg", "jpg", "jpeg", "png", "bmp", "tiff", "tif", "heif", "heic",
}


def _upload_namespace():
    """Execute only upload-policy constants and functions, without app startup."""
    namespace = {"os": os}
    wanted_functions = {
        "config.py": {"get_allowed_extensions", "get_allowed_extension_categories"},
        "functions_documents.py": {"allowed_file", "process_document_upload_background"},
    }
    for filename, names in wanted_functions.items():
        path = APP_DIR / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = []
        found = set()
        for node in tree.body:
            if (
                filename == "config.py"
                and isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Set)
                and any(
                    isinstance(target, ast.Name) and target.id.endswith("EXTENSIONS")
                    for target in node.targets
                )
            ):
                nodes.append(node)
            elif isinstance(node, ast.FunctionDef) and node.name in names:
                nodes.append(node)
                found.add(node.name)
        if found != names:
            raise AssertionError(f"Missing upload functions in {filename}: {names - found}")
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    namespace["ALLOWED_EXTENSIONS"] = namespace["get_allowed_extensions"](True, True)
    return namespace


class OneNoteDevelopmentRevertTests(unittest.TestCase):
    def test_version_remains_monotonic(self):
        assert_app_version_at_least("0.261.046")

    def test_allowlists_reject_native_formats_and_preserve_legacy_formats(self):
        namespace = _upload_namespace()
        for video, audio in product((False, True), repeat=2):
            with self.subTest(video=video, audio=audio):
                allowed = namespace["get_allowed_extensions"](video, audio)
                self.assertTrue(LEGACY_EXTENSIONS.issubset(allowed))
                self.assertTrue(NOTEBOOK_EXTENSIONS.isdisjoint(allowed))
                for enabled, name in ((video, "VIDEO_EXTENSIONS"), (audio, "AUDIO_EXTENSIONS")):
                    self.assertEqual(namespace[name].issubset(allowed), enabled)
                    if not enabled:
                        self.assertTrue(namespace[name].isdisjoint(allowed))
                for extension in LEGACY_EXTENSIONS | NOTEBOOK_EXTENSIONS | {"onetoc2"}:
                    accepted = namespace["allowed_file"](f"fixture.{extension.upper()}", allowed)
                    self.assertEqual(accepted, extension in LEGACY_EXTENSIONS)

    def test_display_categories_preserve_optional_media_and_schema_gates(self):
        namespace = _upload_namespace()
        for video, audio, xsd in product((False, True), repeat=3):
            with self.subTest(video=video, audio=audio, xsd=xsd):
                categories = namespace["get_allowed_extension_categories"](video, audio, xsd)
                extensions = {ext for category in categories for ext in category["extensions"]}
                self.assertTrue((LEGACY_EXTENSIONS - {"xsd"}).issubset(extensions))
                self.assertTrue(NOTEBOOK_EXTENSIONS.isdisjoint(extensions))
                self.assertFalse(any("onenote" in category["name"].lower() for category in categories))
                self.assertEqual("xsd" in extensions, xsd)
                self.assertEqual("mp4" in extensions, video)
                self.assertEqual("mp3" in extensions, audio)

    def test_background_uploads_reject_notebooks_and_clean_up_in_every_scope(self):
        namespace = _upload_namespace()
        scopes = ({}, {"group_id": "group-1"}, {"public_workspace_id": "public-1"})
        for extension, scope in product(("one", "ONE", "onepkg", "ONEPKG"), scopes):
            with self.subTest(extension=extension, scope=scope):
                update = Mock()
                metadata = {"id": "document-1"}
                sync = Mock()
                namespace.update({
                    "get_settings": lambda: {"max_file_size_mb": 16},
                    "update_document": update,
                    "get_document_metadata": Mock(return_value=metadata),
                    "sync_chat_upload_workspace_attachment_status": sync,
                })
                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / f"fixture.{extension}"
                    source.write_bytes(b"Rejected before extraction; not notebook content.")
                    with contextlib.redirect_stdout(io.StringIO()):
                        namespace["process_document_upload_background"](
                            document_id="document-1",
                            user_id="user-1",
                            temp_file_path=str(source),
                            original_filename=source.name,
                            **scope,
                        )
                    source_exists = source.exists()
                update.assert_called_once()
                fields = update.call_args.kwargs
                self.assertEqual(
                    fields["status"],
                    f"Error: Processing failed: File type .{extension.lower()} is not allowed.",
                )
                self.assertEqual(fields["percentage_complete"], 0)
                self.assertEqual(fields["user_id"], "user-1")
                for name, value in scope.items():
                    self.assertEqual(fields[name], value)
                sync.assert_called_once_with(metadata)
                self.assertFalse(source_exists)

    def test_source_classification_retains_legacy_formats_and_stored_text(self):
        path = APP_DIR / "functions_mixed_source_orchestration.py"
        spec = importlib.util.spec_from_file_location("mixed_source_revert_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cases = {
            "notes.ONE": "unsupported",
            "notebook.ONEPKG": "unsupported",
            "document.pdf": "narrative",
            "document.docx": "narrative",
            "notes.txt": "narrative",
            "message.msg": "narrative",
            "diagram.vsdx": "narrative",
            "photo.png": "narrative",
            "sound.mp3": "narrative",
            "video.mp4": "narrative",
            "table.csv": "tabular",
            "table.xlsx": "tabular",
            "schema.xsd": "xml_schema",
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                kind = module.classify_source_kind(filename)
                self.assertEqual(kind, expected)
        existing_kind = module.classify_source_kind("notes.one", {"extracted_text": "Stored text"})
        self.assertEqual(existing_kind, "narrative")

    def test_native_imports_dispatch_and_packaging_are_removed(self):
        paths = [
            APP_DIR / "config.py",
            APP_DIR / "functions_documents.py",
            APP_DIR / "functions_mixed_source_orchestration.py",
            APP_DIR / "Dockerfile",
            ROOT_DIR / ".dockerignore",
            ROOT_DIR / ".gitignore",
        ]
        for path in paths:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8").lower()
                self.assertNotIn("onenote", source)
        self.assertFalse((APP_DIR / "functions_onenote.py").exists())
        self.assertFalse((APP_DIR / "native" / "onenote_extractor").exists())


if __name__ == "__main__":
    unittest.main()
