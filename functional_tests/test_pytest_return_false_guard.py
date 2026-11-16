#!/usr/bin/env python3
# test_pytest_return_false_guard.py
"""
Functional test for the pytest return-False guard.
Version: 0.261.203
Implemented in: 0.261.203

This test ensures that the guard block in functional_tests/conftest.py, and the
identical block in ui_tests/conftest.py, fails a pytest test whose function
returns False (#1572) while leaving every other outcome, test collection and
the test function itself alone.

Each outcome check runs pytest in a subprocess on probe files in a temporary
directory and reads the outcomes from a JUnit XML report. The checks raise
AssertionError explicitly instead of using assert, so they still run under
python -O. A pytest subprocess that does not finish in time is retried. Only
the installed-plugins check depends on the environment: when pytest cannot
start with the installed plugins, or does not finish in any attempt, it is
reported as an environment skip with an excerpt instead of a failure.
"""

import ast
import difflib
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_COPIES = (
    REPO_ROOT / "functional_tests" / "conftest.py",
    REPO_ROOT / "ui_tests" / "conftest.py",
)
GUARD_BLOCK_BEGIN = "# --- begin pytest return-False guard (#1572) ---"
GUARD_BLOCK_END = "# --- end pytest return-False guard (#1572) ---"
GUARD_HOOK_DECORATOR = "pytest.hookimpl(wrapper=True, tryfirst=True)"
GUARD_IMPORTS = frozenset({"functools", "inspect", "pytest"})
GUARD_EXPLANATION = "Under pytest a test that returns False now fails (#1572)"
ASYNC_FAILURE = "async def functions are not natively supported"
COLLECTION_HOOK_PREFIXES = ("pytest_collect", "pytest_pycollect_")
COLLECTION_HOOKS = frozenset({
    "pytest_deselected",
    "pytest_generate_tests",
    "pytest_ignore_collect",
    "pytest_itemcollected",
    "pytest_make_collect_report",
    "pytest_make_parametrize_id",
})
# Module-level names that change what pytest collects or which plugins it loads.
FORBIDDEN_MODULE_SETTINGS = frozenset({"collect_ignore", "collect_ignore_glob", "pytest_plugins"})
# A probe run normally takes a few seconds. A run that stalls is killed and retried.
PYTEST_ATTEMPT_TIMEOUT_SECONDS = 90
PYTEST_ATTEMPTS = 3
PROBE_OUTPUT_FILES = ("junit.xml", "teardown.log")
# pytest exits 1 when a plugin raises while it is imported (an unhandled exception),
# 3 on an internal error and 4 on a usage error. None of them writes a JUnit report.
STARTUP_FAILURE_RETURNCODES = frozenset({1, 3, 4})
PROBE_ENVIRONMENT_OVERRIDES = (
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTHONOPTIMIZE",
    "PYTHONWARNINGS",
    "PYTHONPATH",
)

PROBE_MODULE = '''# test_guard_probe.py
import inspect
import unittest
from pathlib import Path

import pytest


def _helper_returning_false():
    return False


async def _async_false():
    return False


@pytest.fixture
def recorded_value():
    return {"ok": False}


@pytest.fixture
def tracked_resource():
    yield "resource"
    Path(__file__).with_name("teardown.log").write_text("torn down", encoding="utf-8")


def test_returns_false():
    return False


def test_returns_true():
    return True


def test_returns_none_explicitly():
    return None


def test_returns_nothing():
    pass


def test_returns_zero():
    return 0


def test_returns_empty_string():
    return ""


def test_assert_false():
    assert False, "plain assert failure"


def test_raises_value_error():
    raise ValueError("boom from probe")


def test_helper_false_but_test_returns_none():
    _helper_returning_false()


@pytest.mark.parametrize("value", [True, False, None])
def test_param(value):
    return value


def test_fixture_false(recorded_value):
    return recorded_value["ok"]


def test_yield_fixture_false(tracked_resource):
    return tracked_resource == "something else"


def test_signature_preserved(request, recorded_value):
    function = request.function
    if function.__name__ != "test_signature_preserved":
        raise AssertionError(f"name changed: {function.__name__}")
    parameters = list(inspect.signature(function).parameters)
    if parameters != ["request", "recorded_value"]:
        raise AssertionError(f"signature changed: {parameters}")


class TestReturns:
    def test_method_false(self):
        return False

    def test_method_true(self):
        return True

    def test_method_fixture_false(self, recorded_value):
        return recorded_value["ok"]


class ProbeUnitTest(unittest.TestCase):
    def test_unittest_returns_false(self):
        return False


async def test_async_returns_false():
    return False


async def test_async_generator_false():
    yield False


def test_sync_returns_coroutine():
    return _async_false()


def test_zz_objects_restored(request):
    for item in request.session.items:
        if item is request.node:
            break
        if getattr(item.obj, "__wrapped__", None) is not None:
            raise AssertionError(f"{item.nodeid} still runs through the recorder")
'''

NESTED_PROBE_MODULE = '''# test_nested_probe.py


def test_nested_false():
    return False


def test_nested_true():
    return True
'''

# JUnit "classname::name" -> (expected outcome, detail). A "guard" detail is the
# node id the guard message must name; a "failed" detail is text the test's own
# failure message must contain (and the guard must not have claimed it).
PROBE_EXPECTATIONS = {
    "test_guard_probe::test_returns_false": ("guard", "test_guard_probe.py::test_returns_false"),
    "test_guard_probe::test_returns_true": ("passed", None),
    "test_guard_probe::test_returns_none_explicitly": ("passed", None),
    "test_guard_probe::test_returns_nothing": ("passed", None),
    "test_guard_probe::test_returns_zero": ("passed", None),
    "test_guard_probe::test_returns_empty_string": ("passed", None),
    "test_guard_probe::test_assert_false": ("failed", "AssertionError: plain assert failure"),
    "test_guard_probe::test_raises_value_error": ("failed", "ValueError: boom from probe"),
    "test_guard_probe::test_helper_false_but_test_returns_none": ("passed", None),
    "test_guard_probe::test_param[True]": ("passed", None),
    "test_guard_probe::test_param[False]": ("guard", "test_guard_probe.py::test_param[False]"),
    "test_guard_probe::test_param[None]": ("passed", None),
    "test_guard_probe::test_fixture_false": ("guard", "test_guard_probe.py::test_fixture_false"),
    "test_guard_probe::test_yield_fixture_false": ("guard", "test_guard_probe.py::test_yield_fixture_false"),
    "test_guard_probe::test_signature_preserved": ("passed", None),
    "test_guard_probe.TestReturns::test_method_false": (
        "guard",
        "test_guard_probe.py::TestReturns::test_method_false",
    ),
    "test_guard_probe.TestReturns::test_method_true": ("passed", None),
    "test_guard_probe.TestReturns::test_method_fixture_false": (
        "guard",
        "test_guard_probe.py::TestReturns::test_method_fixture_false",
    ),
    "test_guard_probe.ProbeUnitTest::test_unittest_returns_false": ("passed", None),
    "test_guard_probe::test_async_returns_false": ("failed", ASYNC_FAILURE),
    "test_guard_probe::test_async_generator_false": ("failed", ASYNC_FAILURE),
    "test_guard_probe::test_sync_returns_coroutine": ("failed", ASYNC_FAILURE),
    "test_guard_probe::test_zz_objects_restored": ("passed", None),
    "sub.test_nested_probe::test_nested_false": ("guard", "sub/test_nested_probe.py::test_nested_false"),
    "sub.test_nested_probe::test_nested_true": ("passed", None),
}

# An installed async plugin may run these itself; the guard must only never claim them.
ASYNC_CASES = frozenset({
    "test_guard_probe::test_async_returns_false",
    "test_guard_probe::test_async_generator_false",
    "test_guard_probe::test_sync_returns_coroutine",
})


def _tail(output, lines=40):
    return "\n".join(output.strip().splitlines()[-lines:])


def _timeout_output(error):
    parts = []
    for stream in (error.stdout, error.stderr):
        if isinstance(stream, bytes):
            stream = stream.decode("utf-8", "replace")
        parts.append(stream or "")
    return "".join(parts)


def _skip_for_environment(reason):
    """Report a check this environment cannot run as a skip, never as a pass or a failure."""
    print(f"  ENVIRONMENT SKIP: {reason}")
    pytest.skip(f"environment: {reason}")


def _read_guard_file(guard_copy):
    if not guard_copy.is_file():
        raise AssertionError(f"Missing guard file: {guard_copy}")
    return guard_copy.read_text(encoding="utf-8").replace("\r\n", "\n")


def _guard_block(guard_copy):
    """Return (text, begin line, end line) for the code between a file's guard markers."""
    label = guard_copy.relative_to(REPO_ROOT).as_posix()
    lines = _read_guard_file(guard_copy).split("\n")
    begins = [number for number, line in enumerate(lines, start=1) if line.strip() == GUARD_BLOCK_BEGIN]
    ends = [number for number, line in enumerate(lines, start=1) if line.strip() == GUARD_BLOCK_END]
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        raise AssertionError(
            f"{label}: expected one '{GUARD_BLOCK_BEGIN}' line followed by one '{GUARD_BLOCK_END}' "
            f"line, found begin lines {begins} and end lines {ends}."
        )
    return "\n".join(lines[begins[0]:ends[0] - 1]), begins[0], ends[0]


def _is_collection_hook(name):
    return name.startswith(COLLECTION_HOOK_PREFIXES) or name in COLLECTION_HOOKS


def _write_probe(probe_dir, guard_copy):
    shutil.copyfile(guard_copy, probe_dir / "conftest.py")
    (probe_dir / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (probe_dir / "test_guard_probe.py").write_text(PROBE_MODULE, encoding="utf-8")
    nested_dir = probe_dir / "sub"
    nested_dir.mkdir()
    (nested_dir / "test_nested_probe.py").write_text(NESTED_PROBE_MODULE, encoding="utf-8")


def _probe_environment(autoload_plugins):
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in PROBE_ENVIRONMENT_OVERRIDES
    }
    if not autoload_plugins:
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


class PytestDidNotFinish(AssertionError):
    """A pytest subprocess did not finish within the timeout in any attempt."""


def _run_pytest(probe_dir, arguments, optimized=False, autoload_plugins=False, stdin_text=None):
    """
    Run pytest on the probe directory in a subprocess and return (exit code, output).

    An attempt that does not finish within PYTEST_ATTEMPT_TIMEOUT_SECONDS is killed and
    retried, up to PYTEST_ATTEMPTS attempts in all, and each attempt starts without the
    previous attempt's report files. Such stalls come from the machine rather than the
    guard: on Windows, pytest imports readline at startup and the JUnit report records the
    host name, and both can reach a WMI query in Python's platform module that does not
    return while the machine is heavily loaded.
    """
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command += ["-m", "pytest", "-p", "no:cacheprovider", *arguments]
    stdin_options = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
    last_output = ""
    for attempt in range(1, PYTEST_ATTEMPTS + 1):
        for leftover in PROBE_OUTPUT_FILES:
            (probe_dir / leftover).unlink(missing_ok=True)
        try:
            completed = subprocess.run(
                command,
                cwd=probe_dir,
                env=_probe_environment(autoload_plugins),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=PYTEST_ATTEMPT_TIMEOUT_SECONDS,
                **stdin_options,
            )
            return completed.returncode, completed.stdout + completed.stderr
        except subprocess.TimeoutExpired as error:
            last_output = _timeout_output(error)
            print(
                f"  pytest attempt {attempt} of {PYTEST_ATTEMPTS} did not finish within "
                f"{PYTEST_ATTEMPT_TIMEOUT_SECONDS} s."
            )
    raise PytestDidNotFinish(
        f"pytest {' '.join(arguments)} did not finish within {PYTEST_ATTEMPT_TIMEOUT_SECONDS} s in any of "
        f"{PYTEST_ATTEMPTS} attempts. A guard that hangs, or a machine too loaded to start pytest, "
        f"can cause this. Last output:\n{_tail(last_output, 12) or '(no output)'}"
    )


def _check_run(returncode, output, label, expected_returncode):
    if returncode != expected_returncode:
        raise AssertionError(
            f"{label}: pytest exited {returncode}, expected {expected_returncode}.\n{_tail(output)}"
        )
    for marker in ("INTERNALERROR", "PluggyTeardownRaisedWarning"):
        if marker in output:
            raise AssertionError(f"{label}: pytest output contains {marker}.\n{_tail(output)}")


def _read_junit_outcomes(junit_path):
    outcomes = {}
    # The report was just written by our own pytest run into our temporary directory.
    root = ElementTree.parse(junit_path).getroot()
    for case in root.iter("testcase"):
        key = f"{case.get('classname')}::{case.get('name')}"
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            child = case.find(tag)
            if child is not None:
                outcome = "failed" if tag == "failure" else tag
                message = f"{child.get('message') or ''}\n{child.text or ''}"
                break
        outcomes[key] = (outcome, message)
    return outcomes


def _is_guard_message(message):
    return "returned False." in message and GUARD_EXPLANATION in message


def _check_outcomes(outcomes, label, relaxed_keys=frozenset()):
    problems = []
    missing = sorted(set(PROBE_EXPECTATIONS) - set(outcomes))
    unexpected = sorted(set(outcomes) - set(PROBE_EXPECTATIONS))
    if missing:
        problems.append(f"no result for {missing}")
    if unexpected:
        problems.append(f"unexpected tests {unexpected}")

    for key, (expected, detail) in PROBE_EXPECTATIONS.items():
        if key not in outcomes:
            continue
        outcome, message = outcomes[key]
        short_message = " ".join(message.split())[:240]
        if key in relaxed_keys:
            if _is_guard_message(message):
                problems.append(f"{key}: the guard claimed an async test: {short_message}")
            continue
        if expected == "passed":
            if outcome != "passed":
                problems.append(f"{key}: expected passed, got {outcome}: {short_message}")
        elif expected == "guard":
            if outcome != "failed" or f"{detail} returned False." not in message or not _is_guard_message(message):
                problems.append(f"{key}: expected the guard failure naming {detail}, got {outcome}: {short_message}")
        elif outcome != "failed" or detail not in message or _is_guard_message(message):
            problems.append(f"{key}: expected its own failure containing {detail!r}, got {outcome}: {short_message}")

    if problems:
        raise AssertionError(f"{label}:\n  " + "\n  ".join(problems))


def _run_probe_and_check(
    guard_copy,
    label,
    optimized=False,
    autoload_plugins=False,
    relaxed_keys=frozenset(),
    skip_if_pytest_cannot_start=False,
):
    with tempfile.TemporaryDirectory(prefix="return_false_guard_", ignore_cleanup_errors=True) as temp_dir:
        probe_dir = Path(temp_dir)
        _write_probe(probe_dir, guard_copy)
        junit_path = probe_dir / "junit.xml"
        returncode, output = _run_pytest(
            probe_dir,
            ["-q", "-rA", f"--junitxml={junit_path}", "-o", "junit_family=xunit2"],
            optimized=optimized,
            autoload_plugins=autoload_plugins,
        )
        if skip_if_pytest_cannot_start and not junit_path.is_file() and returncode in STARTUP_FAILURE_RETURNCODES:
            _skip_for_environment(
                f"{label}: pytest could not start (exit {returncode}, no JUnit report), most likely "
                f"because an installed plugin failed to load:\n{_tail(output, 12)}"
            )
        _check_run(returncode, output, label, expected_returncode=1)
        if not junit_path.is_file():
            raise AssertionError(f"{label}: pytest wrote no JUnit report.\n{_tail(output)}")
        outcomes = _read_junit_outcomes(junit_path)
        _check_outcomes(outcomes, label, relaxed_keys)
        teardown_log = probe_dir / "teardown.log"
        if not teardown_log.is_file() or teardown_log.read_text(encoding="utf-8") != "torn down":
            raise AssertionError(f"{label}: the yield fixture's teardown did not run after the guard failure")
    print(f"  {label}: all {len(outcomes)} probe outcomes as expected.")


def test_guard_blocks_are_identical():
    """The functional_tests and ui_tests guard blocks must stay the same code."""
    print("Testing the two guard blocks are identical...")
    blocks = [_guard_block(guard_copy)[0] for guard_copy in GUARD_COPIES]
    if blocks[0] != blocks[1]:
        labels = [guard_copy.relative_to(REPO_ROOT).as_posix() for guard_copy in GUARD_COPIES]
        difference = "\n".join(
            difflib.unified_diff(
                blocks[0].splitlines(), blocks[1].splitlines(), labels[0], labels[1], lineterm=""
            )
        )
        raise AssertionError(f"The guard blocks differ; keep them identical.\n{_tail(difference)}")
    print(f"  Both guard blocks are identical ({len(blocks[0].splitlines())} lines).")


def test_guard_block_only_wraps_the_call_hook():
    """Each guard is one tryfirst pytest_pyfunc_call wrapper that leaves collection, sys.path and sys.modules alone."""
    print("Testing each guard block defines only the pytest_pyfunc_call wrapper...")
    for guard_copy in GUARD_COPIES:
        label = guard_copy.relative_to(REPO_ROOT).as_posix()
        block_text, begin_line, end_line = _guard_block(guard_copy)
        file_tree = ast.parse(_read_guard_file(guard_copy))

        hooks = [
            node
            for node in ast.walk(file_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "pytest_pyfunc_call"
        ]
        if len(hooks) != 1:
            raise AssertionError(f"{label}: expected exactly one pytest_pyfunc_call, found {len(hooks)}.")
        hook = hooks[0]
        first_line = min([hook.lineno] + [decorator.lineno for decorator in hook.decorator_list])
        if hook not in file_tree.body or not begin_line < first_line <= hook.end_lineno < end_line:
            raise AssertionError(f"{label}: pytest_pyfunc_call must be a module-level function inside the guard block.")
        decorators = [ast.unparse(decorator) for decorator in hook.decorator_list]
        if decorators != [GUARD_HOOK_DECORATOR]:
            raise AssertionError(
                f"{label}: pytest_pyfunc_call must be decorated {GUARD_HOOK_DECORATOR}, got {decorators}."
            )

        block_tree = ast.parse(block_text)
        imported = set()
        for node in ast.walk(block_tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add("." * node.level + (node.module or ""))
        if imported != GUARD_IMPORTS:
            raise AssertionError(
                f"{label}: the guard block imports {sorted(imported)}; expected only {sorted(GUARD_IMPORTS)}."
            )
        block_hooks = sorted(
            node.name
            for node in block_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("pytest_")
        )
        if block_hooks != ["pytest_pyfunc_call"]:
            raise AssertionError(f"{label}: the guard block defines hooks {block_hooks}; expected only pytest_pyfunc_call.")

        for node in file_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_collection_hook(node.name):
                raise AssertionError(f"{label}: defines the collection hook {node.name}.")
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            else:
                targets = []
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            if names & FORBIDDEN_MODULE_SETTINGS:
                raise AssertionError(
                    f"{label}: sets {sorted(names & FORBIDDEN_MODULE_SETTINGS)}, which changes collection or plugins."
                )
        print(f"  {label}: one tryfirst pytest_pyfunc_call wrapper inside the block, no collection hooks.")


def test_guard_outcomes_for_each_copy():
    """Each copy fails exactly the tests that return False and leaves every other outcome alone."""
    print("Testing probe outcomes with each guard copy...")
    for guard_copy in GUARD_COPIES:
        _run_probe_and_check(guard_copy, guard_copy.relative_to(REPO_ROOT).as_posix())


def test_guard_outcomes_under_optimized_python():
    """The guard does not rely on assert, so python -O -m pytest gives the same outcomes."""
    print("Testing probe outcomes under python -O -m pytest...")
    _run_probe_and_check(GUARD_COPIES[0], "python -O -m pytest", optimized=True)


def test_guard_outcomes_with_installed_plugins():
    """
    Installed pytest plugins (anyio, pytest-asyncio, playwright, ...) do not change the guard.

    This is the only check that depends on the environment. If pytest cannot start with the
    installed plugins, or does not finish in any attempt, the check is reported as an
    environment skip with an excerpt instead of failing.
    """
    print("Testing probe outcomes with installed pytest plugins autoloaded...")
    try:
        _run_probe_and_check(
            GUARD_COPIES[0],
            "installed plugins autoloaded",
            autoload_plugins=True,
            relaxed_keys=ASYNC_CASES,
            skip_if_pytest_cannot_start=True,
        )
    except PytestDidNotFinish as error:
        _skip_for_environment(f"installed plugins autoloaded: {error}")


def test_guard_survives_pytest_trace():
    """pytest --trace wraps the test function too; tryfirst keeps the guard's recorder innermost."""
    print("Testing the guard still fails a returned False under pytest --trace...")
    with tempfile.TemporaryDirectory(prefix="return_false_guard_", ignore_cleanup_errors=True) as temp_dir:
        probe_dir = Path(temp_dir)
        _write_probe(probe_dir, GUARD_COPIES[0])
        returncode, output = _run_pytest(
            probe_dir,
            ["-q", "--trace", "sub/test_nested_probe.py::test_nested_false"],
            stdin_text="c\nc\nc\n",
        )
        _check_run(returncode, output, "pytest --trace", expected_returncode=1)
        if "sub/test_nested_probe.py::test_nested_false returned False." not in output or GUARD_EXPLANATION not in output:
            raise AssertionError(f"pytest --trace: the guard message is missing.\n{_tail(output)}")
    print("  The guard failure survives pytest --trace.")


def test_guard_leaves_collection_unchanged():
    """The guard collects exactly what pytest collects without it."""
    print("Testing collection is identical with and without the guard...")
    with tempfile.TemporaryDirectory(prefix="return_false_guard_", ignore_cleanup_errors=True) as temp_dir:
        probe_dir = Path(temp_dir)
        _write_probe(probe_dir, GUARD_COPIES[0])
        returncode, with_guard = _run_pytest(probe_dir, ["--collect-only", "-q"])
        _check_run(returncode, with_guard, "--collect-only", expected_returncode=0)
        returncode, without_guard = _run_pytest(probe_dir, ["--collect-only", "-q", "--noconftest"])
        _check_run(returncode, without_guard, "--collect-only --noconftest", expected_returncode=0)
    ids_with_guard = [line.strip() for line in with_guard.splitlines() if "::" in line]
    ids_without_guard = [line.strip() for line in without_guard.splitlines() if "::" in line]
    if len(ids_with_guard) != len(PROBE_EXPECTATIONS) or ids_with_guard != ids_without_guard:
        raise AssertionError(
            f"Collection differs: {len(ids_with_guard)} ids with the guard, "
            f"{len(ids_without_guard)} without, {len(PROBE_EXPECTATIONS)} expected."
        )
    print(f"  The same {len(ids_with_guard)} test ids are collected with and without the guard.")


if __name__ == "__main__":
    tests = [
        test_guard_blocks_are_identical,
        test_guard_block_only_wraps_the_call_hook,
        test_guard_outcomes_for_each_copy,
        test_guard_outcomes_under_optimized_python,
        test_guard_outcomes_with_installed_plugins,
        test_guard_survives_pytest_trace,
        test_guard_leaves_collection_unchanged,
    ]
    outcomes = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            outcomes.append("passed")
        except pytest.skip.Exception as skip:
            print(f"Skipped: {skip.msg}")
            outcomes.append("skipped")
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test failed: {error}")
            traceback.print_exc()
            outcomes.append("failed")

    skipped = outcomes.count("skipped")
    skipped_note = f", {skipped} skipped (environment)" if skipped else ""
    print(f"\nResults: {outcomes.count('passed')}/{len(outcomes)} tests passed{skipped_note}")
    sys.exit(1 if "failed" in outcomes else 0)
