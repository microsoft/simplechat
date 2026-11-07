# test_onenote_native_integration.py
"""
Functional tests for the packaged OneNote executable and Python adapter.
Version: 0.261.142
Implemented in: 0.261.142 (ported from 0.261.045)

Set SIMPLECHAT_ONENOTE_NATIVE_TESTS=1 with a built extractor to enable these
checks. Optional private fixtures are supplied through environment variables,
never committed or printed. The suite can run with network access disabled.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_onenote_extractor_runtime import APP_ROOT, onenote


@unittest.skipUnless(
    os.getenv("SIMPLECHAT_ONENOTE_NATIVE_TESTS") == "1",
    "Set SIMPLECHAT_ONENOTE_NATIVE_TESTS=1 to exercise the installed native component.",
)
class OneNoteNativeIntegrationTests(unittest.TestCase):
    def test_packaged_revision_matches_protocol(self):
        executable = onenote._extractor_path()
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            timeout=10,
            env=onenote._worker_environment(),
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn(onenote.ONENOTE_PARSER_REVISION.encode(), completed.stdout)
        self.assertEqual(completed.stderr, b"")

    def test_real_public_section_retains_friendly_name(self):
        fixture = APP_ROOT / "native" / "onenote_extractor" / "tests" / "fixtures" / "New Section 1.one"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "random-upload-identifier.ONE"
            shutil.copyfile(fixture, source)
            result = onenote.extract_onenote(
                source, 1024 * 1024, original_filename="Friendly Section.ONE"
            )
        self.assertEqual(result.sections, 1)
        self.assertGreater(len(result.pages), 0)
        self.assertTrue(all(page.section_path == ("Friendly Section",) for page in result.pages))
        self.assertTrue(any(page.text.strip() for page in result.pages))

    def test_native_failure_is_stable_and_has_no_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.onepkg"
            source.write_bytes(b"not a cabinet or OneNote package")
            with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                onenote.extract_onenote(source, 1024, original_filename="Invalid.onepkg")
        self.assertEqual(caught.exception.code, "invalid_file")
        self.assertNotIn("invalid.onepkg", str(caught.exception))

    def test_private_exports_are_complete_and_share_standalone_body(self):
        section_path = os.getenv("SIMPLECHAT_ONENOTE_SECTION_FIXTURE")
        package_path = os.getenv("SIMPLECHAT_ONENOTE_PACKAGE_FIXTURE")
        if not section_path or not package_path:
            self.skipTest("Private fixture paths were not supplied.")
        standalone = onenote.extract_onenote(
            section_path, 128 * 1024 * 1024, original_filename="Standalone Notes.one"
        )
        package = onenote.extract_onenote(
            package_path, 128 * 1024 * 1024, original_filename="Notebook.onepkg"
        )
        self.assertEqual(standalone.sections, 1)
        self.assertTrue(any(page.text.strip() for page in standalone.pages))
        self.assertGreater(package.sections, 0)
        self.assertGreater(len(package.pages), 0)
        normalized_bodies = {" ".join(page.text.split()) for page in package.pages}
        self.assertTrue(
            all(" ".join(page.text.split()) in normalized_bodies for page in standalone.pages if page.text.strip()),
            "The standalone page body was not preserved in the notebook.",
        )
        for variable, actual in (
            ("SIMPLECHAT_ONENOTE_EXPECTED_SECTIONS", package.sections),
            ("SIMPLECHAT_ONENOTE_EXPECTED_PAGES", len(package.pages)),
            ("SIMPLECHAT_ONENOTE_EXPECTED_NONEMPTY", sum(bool(page.text.strip()) for page in package.pages)),
        ):
            expected = os.getenv(variable)
            if expected is not None:
                self.assertEqual(actual, int(expected), f"{variable} does not match the extraction count.")
        self.assertEqual(
            package.excluded_content["empty_pages"],
            sum(not page.text.strip() for page in package.pages),
        )

    def test_private_package_respects_application_upload_limit(self):
        package_path = os.getenv("SIMPLECHAT_ONENOTE_PACKAGE_FIXTURE")
        if not package_path:
            self.skipTest("Private package path was not supplied.")
        source = Path(package_path)
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            onenote.extract_onenote(source, source.stat().st_size - 1)
        self.assertEqual(caught.exception.code, "file_too_large")


if __name__ == "__main__":
    unittest.main()
