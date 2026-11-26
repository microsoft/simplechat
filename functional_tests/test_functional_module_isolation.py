#!/usr/bin/env python3
# test_functional_module_isolation.py
"""
Functional test for per-test-file sys.modules isolation.
Version: 0.261.489
Implemented in: 0.261.489

This test ensures that a stub one test file installs in sys.modules does not
leak into the next file, and that modules a stubbing file's module-scoped
fixture installs stay available to all of that file's tests.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


PLUGIN = Path(__file__).resolve().parent / "test_support" / "module_isolation.py"

STUBBING_FILE = '''
import sys, types
import pytest

sys.modules["functions_isolation_probe"] = types.ModuleType("functions_isolation_probe")
sys.modules["functions_isolation_probe"].value = "stub"


@pytest.fixture(scope="module", autouse=True)
def fixture_module():
    module = types.ModuleType("functions_isolation_fixture")
    sys.modules["functions_isolation_fixture"] = module
    yield module


def test_stub_present_first():
    assert sys.modules["functions_isolation_probe"].value == "stub"
    assert "functions_isolation_fixture" in sys.modules


def test_fixture_module_still_present():
    assert "functions_isolation_fixture" in sys.modules
'''

LATER_FILE = '''
import sys


def test_no_stub_leaks():
    assert "functions_isolation_probe" not in sys.modules
    assert "functions_isolation_fixture" not in sys.modules
'''


def test_stubs_stay_with_their_file():
    root = Path(tempfile.mkdtemp())
    try:
        # Same layout as the repository, so the probe names count as application modules.
        app = root / "application" / "single_app"
        app.mkdir(parents=True)
        for name in ("functions_isolation_probe", "functions_isolation_fixture"):
            (app / f"{name}.py").write_text("", encoding="utf-8")
        work = root / "functional_tests"
        (work / "test_support").mkdir(parents=True)
        (work / "test_support" / "__init__.py").write_text("", encoding="utf-8")
        shutil.copy(PLUGIN, work / "test_support" / "module_isolation.py")
        (work / "conftest.py").write_text(
            "import os, sys\n"
            "sys.path.insert(0, os.path.dirname(__file__))\n"
            "from test_support.module_isolation import pytest_make_collect_report, pytest_runtest_protocol\n",
            encoding="utf-8",
        )
        (work / "test_a_stubbing.py").write_text(STUBBING_FILE, encoding="utf-8")
        (work / "test_b_later.py").write_text(LATER_FILE, encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if key != "SIMPLECHAT_TEST_MODULE_ISOLATION"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(work)],
            cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "3 passed" in result.stdout, result.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    try:
        test_stubs_stay_with_their_file()
        print("Test passed!")
        sys.exit(0)
    except Exception as error:
        print(f"Test failed: {error}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
