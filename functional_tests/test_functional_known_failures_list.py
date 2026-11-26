#!/usr/bin/env python3
# test_functional_known_failures_list.py
"""
Functional test for the functional suite's known-failures list.
Version: 0.261.489
Implemented in: 0.261.489

This test ensures that functional_tests/known_failures.txt parses, names only
test files that exist, and that the plugin marks a listed failing test as
xfailed, fails the run when a listed test passes, and leaves listed files
uncollected.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.known_failures import LIST_FILE_NAME, parse_known_failures  # noqa: E402


TEST_DIR = Path(__file__).resolve().parent
PLUGIN = TEST_DIR / "test_support" / "known_failures.py"


def test_list_parses_and_names_existing_files():
    """Every entry has a reason and points at a test file in functional_tests/."""
    tests, files = parse_known_failures((TEST_DIR / LIST_FILE_NAME).read_text(encoding="utf-8"))
    missing = sorted({entry.split("::")[0] for entry in [*tests, *files]
                      if not (TEST_DIR / entry.split("::")[0]).is_file()})
    assert not missing, f"{LIST_FILE_NAME} names test files that no longer exist: {missing}"


def test_parser_rejects_entries_without_reason_or_listed_twice():
    for text in ("test_a.py::test_x\n", "test_a.py  # r\ntest_a.py  # r\n"):
        try:
            parse_known_failures(text)
        except ValueError:
            continue
        raise AssertionError(f"accepted invalid list: {text!r}")


def test_plugin_expects_listed_failures_and_rejects_fixed_ones():
    """Run pytest on a throwaway directory that uses the real plugin."""
    work = Path(tempfile.mkdtemp())
    try:
        (work / "test_support").mkdir()
        (work / "test_support" / "__init__.py").write_text("", encoding="utf-8")
        shutil.copy(PLUGIN, work / "test_support" / "known_failures.py")
        (work / "conftest.py").write_text(
            "import os, sys\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "def pytest_configure(config):\n"
            "    from test_support.known_failures import register\n"
            "    register(config, os.path.dirname(os.path.abspath(__file__)))\n",
            encoding="utf-8",
        )
        (work / "test_sample.py").write_text(
            "def test_still_broken():\n    assert False\n\n"
            "def test_fixed():\n    assert True\n\n"
            "def test_unlisted():\n    assert True\n\n"
            "import unittest\n\n"
            "class Subtests(unittest.TestCase):\n"
            "    def test_some_broken(self):\n"
            "        for value in (1, 2):\n"
            "            with self.subTest(value=value):\n"
            "                self.assertEqual(value, 1)\n\n"
            "    def test_all_fixed(self):\n"
            "        with self.subTest(value=1):\n"
            "            self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )
        (work / "test_cannot_import.py").write_text("raise ImportError('gone')\n", encoding="utf-8")
        (work / LIST_FILE_NAME).write_text(
            "# sample\n"
            "test_sample.py::test_still_broken  # stub out of date\n"
            "test_sample.py::test_fixed         # was broken\n"
            "test_sample.py::Subtests::test_some_broken  # subtest out of date\n"
            "test_sample.py::Subtests::test_all_fixed    # was broken\n"
            "test_cannot_import.py              # whole file: import fails\n",
            encoding="utf-8",
        )
        env = {key: value for key, value in os.environ.items() if key != "SIMPLECHAT_IGNORE_KNOWN_FAILURES"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rxX", str(work)],
            cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        )
        output = result.stdout + result.stderr
        # test_still_broken, test_some_broken and its failing subtest are xfailed;
        # test_fixed and test_all_fixed pass, so each fails the run as XPASS(strict).
        assert "2 failed, 1 passed, 3 xfailed, 2 subtests passed" in output, output
        assert "XPASS(strict)" in output and "test_fixed" in output and "test_all_fixed" in output, output
        assert "error" not in output.lower(), output
        assert result.returncode == 1, output

        env["SIMPLECHAT_IGNORE_KNOWN_FAILURES"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(work / "test_sample.py")],
            cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        )
        assert "2 failed, 4 passed" in result.stdout, result.stdout
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        test_list_parses_and_names_existing_files()
        test_parser_rejects_entries_without_reason_or_listed_twice()
        test_plugin_expects_listed_failures_and_rejects_fixed_ones()
        print("Test passed!")
        sys.exit(0)
    except Exception as error:
        print(f"Test failed: {error}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
