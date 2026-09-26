# test_onenote_extractor_runtime.py
"""
Functional tests for bounded local OneNote extraction.
Version: 0.261.045
Implemented in: 0.261.045

Exercises the real Python adapter and real child processes without Azure I/O.
Private notebooks are never test fixtures committed to the repository.
"""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


def load_adapter():
    spec = importlib.util.spec_from_file_location("onenote_runtime_test_module", APP_ROOT / "functions_onenote.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {spec.name: module}):
        spec.loader.exec_module(module)
    return module


onenote = load_adapter()


def result_payload():
    return {
        "protocol_version": 1,
        "parser_revision": onenote.ONENOTE_PARSER_REVISION,
        "sections": 1,
        "source_pages": 1,
        "pages": [{
            "section_path": ["Reference", "Notes"],
            "id": "page-1",
            "title": "Example",
            "level": 1,
            "text": "Item\tQuantity\nCobalt widgets\t17",
        }],
        "excluded_content": {"images": 0, "ink": 0, "attachments": 0, "empty_pages": 0},
    }


class OneNoteProtocolTests(unittest.TestCase):
    def validate(self, payload, return_code=0):
        return onenote._validate_result(return_code, json.dumps(payload).encode("utf-8"))

    def assert_error_code(self, code, callback):
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_complete_typed_result(self):
        result = self.validate(result_payload())
        self.assertEqual(result.sections, 1)
        self.assertEqual(result.pages[0].section_path, ("Reference", "Notes"))
        self.assertIn("Cobalt widgets\t17", result.pages[0].text)

    def test_failed_worker_only_exposes_known_message(self):
        payload = {"protocol_version": 1, "error": {"code": "incomplete_notebook", "detail": "private server path"}}
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            self.validate(payload, 2)
        self.assertEqual(caught.exception.code, "incomplete_notebook")
        self.assertNotIn("private server path", str(caught.exception))

    def test_unknown_error_is_not_reflected(self):
        self.assert_error_code(
            "extraction_failed",
            lambda: self.validate({"protocol_version": 1, "error": {"code": "private failure"}}, 2),
        )

    def test_schema_and_counts_are_strict(self):
        mutations = [
            lambda p: p.update(protocol_version=True),
            lambda p: p.update(parser_revision="incompatible"),
            lambda p: p.update(sections=False),
            lambda p: p.update(source_pages=2),
            lambda p: p.update(pages="invalid"),
            lambda p: p["pages"][0].update(level=0),
            lambda p: p["pages"][0].update(level=True),
            lambda p: p["pages"][0].update(section_path=[]),
            lambda p: p["pages"][0].update(section_path=["x"] * 17),
            lambda p: p["pages"][0].update(title="x" * 4097),
            lambda p: p["pages"][0].update(text=None),
            lambda p: p["pages"][0].update(text="\0"),
            lambda p: p["pages"][0].update(text="\ud800"),
            lambda p: p["excluded_content"].update(empty_pages=1),
            lambda p: p["excluded_content"].update(images=-1),
            lambda p: p["excluded_content"].update(ink=False),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                payload = result_payload()
                mutate(payload)
                self.assert_error_code("invalid_output", lambda: self.validate(payload))

    def test_all_empty_pages_are_not_success(self):
        payload = result_payload()
        payload["pages"][0]["text"] = " \n\t"
        payload["excluded_content"]["empty_pages"] = 1
        self.assert_error_code("no_text", lambda: self.validate(payload))

    def test_unicode_text_budget_counts_utf8_bytes(self):
        payload = result_payload()
        payload["pages"][0]["text"] = "\u4e2d\u6587"
        with patch.object(onenote, "ONENOTE_MAX_TEXT_BYTES", 6):
            result = self.validate(payload)
        self.assertEqual(result.pages[0].text, "\u4e2d\u6587")
        with patch.object(onenote, "ONENOTE_MAX_TEXT_BYTES", 5):
            self.assert_error_code("limit_exceeded", lambda: self.validate(payload))

    def test_aggregate_text_limit_is_enforced(self):
        payload = result_payload()
        payload["pages"][0]["text"] = "abc"
        second = copy.deepcopy(payload["pages"][0])
        second["id"] = "page-2"
        payload["pages"].append(second)
        payload["source_pages"] = 2
        with patch.object(onenote, "ONENOTE_MAX_TEXT_BYTES", 5):
            self.assert_error_code("limit_exceeded", lambda: self.validate(payload))

    def test_malformed_json_is_safe(self):
        self.assert_error_code("invalid_output", lambda: onenote._validate_result(0, b"{invalid"))

    def test_os_terminated_worker_has_safe_failure(self):
        self.assert_error_code("extraction_failed", lambda: onenote._validate_result(1, b""))


class OneNoteProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "fixture.ONE"
        self.source.write_bytes(b"source")

    def run_script(self, script, original_filename=None):
        real_popen = subprocess.Popen
        processes = []

        def launch(command, **kwargs):
            expected = [str(Path(sys.executable)), str(self.source)]
            if original_filename is not None:
                expected.append(original_filename)
            self.assertEqual(command, expected)
            self.assertFalse(kwargs["shell"])
            self.assertNotIn("SIMPLECHAT_TEST_SECRET", kwargs["env"])
            process = real_popen([sys.executable, "-c", script], **kwargs)
            processes.append(process)
            return process

        with patch.dict(os.environ, {"SIMPLECHAT_TEST_SECRET": "test-only"}):
            with patch.object(onenote.subprocess, "Popen", side_effect=launch):
                try:
                    result = onenote._run_extractor(Path(sys.executable), self.source, original_filename)
                finally:
                    for process in processes:
                        self.assertIsNotNone(process.poll())
        return result

    def test_real_child_process_result(self):
        payload = json.dumps(result_payload())
        return_code, output = self.run_script(f"import sys; sys.stdout.write({payload!r})")
        result = onenote._validate_result(return_code, output)
        self.assertEqual(len(result.pages), 1)

    def test_friendly_filename_is_a_single_argument_not_a_shell_command(self):
        payload = json.dumps(result_payload())
        label = "My Notes & More's.ONE"
        return_code, output = self.run_script(f"import sys; sys.stdout.write({payload!r})", label)
        result = onenote._validate_result(return_code, output)
        self.assertEqual(result.sections, 1)

    def test_stdout_limit_kills_and_reaps_worker(self):
        with patch.object(onenote, "ONENOTE_MAX_OUTPUT_BYTES", 128):
            with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                self.run_script("import sys; sys.stdout.write('x' * 1000000); sys.stdout.flush()")
        self.assertEqual(caught.exception.code, "limit_exceeded")

    def test_stderr_limit_kills_and_reaps_worker(self):
        with patch.object(onenote, "ONENOTE_STDERR_LIMIT_BYTES", 128):
            with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                self.run_script("import sys; sys.stderr.write('x' * 1000000); sys.stderr.flush()")
        self.assertEqual(caught.exception.code, "limit_exceeded")

    def test_timeout_kills_and_reaps_worker(self):
        with patch.object(onenote, "ONENOTE_TIMEOUT_SECONDS", 0.1):
            with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                self.run_script("import time; time.sleep(10)")
        self.assertEqual(caught.exception.code, "timeout")

    def test_missing_runtime_error_is_actionable(self):
        with patch.dict(os.environ, {"SIMPLECHAT_ONENOTE_EXTRACTOR": str(self.source.parent / "missing.exe")}):
            with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                onenote.extract_onenote(self.source, 1024)
        self.assertEqual(caught.exception.code, "runtime_unavailable")
        self.assertNotIn(str(self.source.parent), str(caught.exception))

    def test_input_size_boundary_precedes_execution(self):
        payload = json.dumps(result_payload()).encode("utf-8")
        with patch.object(onenote, "_extractor_path", return_value=Path(sys.executable)):
            with patch.object(onenote, "_run_extractor", return_value=(0, payload)) as run:
                result = onenote.extract_onenote(self.source, 6)
                self.assertEqual(len(result.pages), 1)
                with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                    onenote.extract_onenote(self.source, 5)
                self.assertEqual(caught.exception.code, "file_too_large")
                self.assertEqual(run.call_count, 1)

    def test_native_input_cap_cannot_be_raised_by_app_setting(self):
        with patch.object(onenote, "ONENOTE_MAX_INPUT_BYTES", 5):
            with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                onenote.extract_onenote(self.source, 1024)
        self.assertEqual(caught.exception.code, "file_too_large")

    def test_friendly_filename_is_forwarded_unchanged(self):
        payload = json.dumps(result_payload()).encode("utf-8")
        with patch.object(onenote, "_extractor_path", return_value=Path(sys.executable)):
            with patch.object(onenote, "_run_extractor", return_value=(0, payload)) as run:
                result = onenote.extract_onenote(self.source, 1024, original_filename="Original Section.ONE")
        self.assertEqual(len(result.pages), 1)
        self.assertEqual(run.call_args.args[2], "Original Section.ONE")

    def test_invalid_friendly_filename_never_starts_worker(self):
        for label in ("../escape.one", "group\\notes.one", "C:notes.one", "\ud800.one", ".one", "notes.txt", "notes\n.one", ""):
            with self.subTest(label=repr(label)):
                with patch.object(onenote, "_run_extractor") as run:
                    with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                        onenote.extract_onenote(self.source, 1024, original_filename=label)
                self.assertEqual(caught.exception.code, "invalid_file")
                run.assert_not_called()

    def test_semaphore_is_released_on_worker_failure(self):
        slot = onenote.threading.BoundedSemaphore(1)
        with patch.object(onenote, "_EXTRACTION_SLOT", slot):
            with patch.object(onenote, "_extractor_path", return_value=Path(sys.executable)):
                with patch.object(onenote, "_run_extractor", side_effect=onenote.OneNoteExtractionError("timeout")):
                    with self.assertRaises(onenote.OneNoteExtractionError):
                        onenote.extract_onenote(self.source, 1024)
            acquired = slot.acquire(blocking=False)
            self.assertTrue(acquired)
            if acquired:
                slot.release()

    def test_invalid_source_path_is_a_safe_error(self):
        for source in (None, "bad\0path.one"):
            with self.subTest(source_type=type(source).__name__):
                with self.assertRaises(onenote.OneNoteExtractionError) as caught:
                    onenote.extract_onenote(source, 1024)
                self.assertEqual(caught.exception.code, "invalid_file")

    def test_bootstrap_modules_are_not_imported(self):
        script = (
            "import sys; "
            f"sys.path.insert(0, {str(APP_ROOT)!r}); "
            "import functions_onenote; "
            "blocked={'config','functions_settings','functions_appinsights'}; "
            "raise SystemExit(1 if blocked.intersection(sys.modules) else 0)"
        )
        completed = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=20, check=False)
        self.assertEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
