# test_v2_onenote_uploads.py
"""
Functional coverage for the native OneNote port to React v2.
Version: 0.261.142
Implemented in: 0.261.142

Execute the shared format catalog and v2 projection with isolated storage state.
Keep workspace formats separate from chat, prove the real adapter imports
without application bootstrap or network access, and pin the combined image
stage wiring. Actual native/container and browser execution have separate tests.
"""

import ast
import copy
import subprocess
import sys
import unittest
from pathlib import Path

from test_onenote_upload_dispatch import APP_ROOT, chunk_tests, config_namespace
from test_support.versioning import assert_app_version_at_least


ROOT = APP_ROOT.parents[1]
BACKEND = APP_ROOT / "route_backend_v2.py"


def upload_catalog(settings=None, *, storage_available=False):
    namespace = config_namespace()
    namespace["CLIENTS"] = {
        "storage_account_office_docs_client": object() if storage_available else None,
    }
    chunk_tests.load_functions(BACKEND, ["_build_workspace_uploads"], namespace)
    return namespace["_build_workspace_uploads"](settings or {})


def extensions(catalog):
    return {
        extension
        for category in catalog["categories"]
        for extension in category["extensions"]
    }


class V2OneNoteUploadTests(unittest.TestCase):
    def test_implementation_version(self):
        assert_app_version_at_least("0.261.142")

    def test_native_formats_use_the_shared_workspace_catalog(self):
        catalog = upload_catalog()
        available = extensions(catalog)
        self.assertTrue({"one", "onepkg", "pdf", "docx", "txt", "csv", "msg", "vsdx"} <= available)
        self.assertTrue({"onetoc2", "exe", "mp4", "mp3", "xsd"}.isdisjoint(available))
        categories = config_namespace()["get_allowed_extension_categories"]()
        self.assertEqual(catalog, {"categories": categories})
        self.assertIn(
            {"name": "OneNote (typed text and tables)", "extensions": ["one", "onepkg"]},
            categories,
        )

    def test_audio_video_gates_match_classic_uploads(self):
        for enabled in (True, "True", "true"):
            with self.subTest(enabled=enabled):
                catalog = upload_catalog({
                    "enable_audio_file_support": enabled,
                    "enable_video_file_support": enabled,
                })
                available = extensions(catalog)
                self.assertTrue({"one", "onepkg", "mp3", "mp4"} <= available)
        for disabled in (False, "False", "false", None):
            with self.subTest(disabled=disabled):
                catalog = upload_catalog({
                    "enable_audio_file_support": disabled,
                    "enable_video_file_support": disabled,
                })
                available = extensions(catalog)
                self.assertTrue({"mp3", "mp4"}.isdisjoint(available))

    def test_schema_gate_still_requires_citations_and_storage(self):
        for citations, storage in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(citations=citations, storage=storage):
                catalog = upload_catalog(
                    {"enable_enhanced_citations": citations}, storage_available=storage,
                )
                available = extensions(catalog)
                self.assertEqual("xsd" in available, citations and storage)
                self.assertTrue({"one", "onepkg"} <= available)

    def test_catalog_is_only_format_metadata(self):
        settings = {"azure_openai_key": "fixture-secret", "internal_endpoint": "https://internal.invalid"}
        before = copy.deepcopy(settings)
        actual = upload_catalog(settings)
        expected = upload_catalog()
        self.assertEqual(actual, expected)
        self.assertEqual(settings, before)

    def test_bootstrap_projects_formats_from_sanitized_settings(self):
        tree = ast.parse(BACKEND.read_text(encoding="utf-8"))
        bootstrap = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "v2_bootstrap"
        )
        payload = next(
            node.value for node in ast.walk(bootstrap)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "payload" for target in node.targets)
        )
        projection = next(
            value for key, value in zip(payload.keys, payload.values)
            if isinstance(key, ast.Constant) and key.value == "workspace_uploads"
        )
        self.assertEqual(ast.unparse(projection), "_build_workspace_uploads(public_settings)")

    def test_real_adapter_cold_import_never_initializes_the_app(self):
        probe = """
import socket
import sys
def forbidden(*args, **kwargs):
    raise RuntimeError("Network access is forbidden during adapter import")
socket.socket = forbidden
socket.create_connection = forbidden
sys.path.insert(0, sys.argv[1])
import functions_onenote
if any(name in sys.modules for name in ("config", "functions_settings", "functions_appinsights")):
    raise RuntimeError("OneNote adapter crossed the application bootstrap boundary")
if functions_onenote.OneNoteExtractionError("runtime_unavailable").code != "runtime_unavailable":
    raise RuntimeError("The real adapter was not loaded")
"""
        for optimization in ([], ["-O"]):
            with self.subTest(optimization=optimization):
                result = subprocess.run(
                    [sys.executable, "-I", *optimization, "-c", probe, str(APP_ROOT)],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_final_image_contains_both_native_runtime_and_built_spa(self):
        dockerfile = (APP_ROOT / "Dockerfile").read_text(encoding="utf-8")
        final_stage = dockerfile.rsplit("\nFROM ", 1)[1]
        self.assertTrue(final_stage.startswith("onenote-runtime\n"))
        self.assertIn("AS v2uibuilder", dockerfile)
        self.assertIn("AS onenote-builder", dockerfile)
        self.assertIn("AS onenote-runtime", dockerfile)
        self.assertIn("cargo build --release --locked", dockerfile)
        self.assertIn("COPY --from=onenote-builder /build/target/release/simplechat-onenote-extractor", dockerfile)
        self.assertIn("COPY --from=onenote-builder /onenote-source/", dockerfile)
        self.assertIn("COPY --from=v2uibuilder", final_stage)
        self.assertLess(
            final_stage.index("application/single_app ./"),
            final_stage.index("COPY --from=v2uibuilder"),
        )
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        for path in (
            "application/v2_ui/node_modules/",
            "application/single_app/static/v2/",
            "application/single_app/native/onenote_extractor/target/",
            "application/single_app/native/onenote_extractor/bin/",
        ):
            self.assertIn(path, ignored)
        self.assertIn("!LICENSE", ignored)


if __name__ == "__main__":
    unittest.main()
