# run_tests.py
"""Run the SimpleChat test suites with the flags each one needs.

Version: 0.261.489
Implemented in: 0.261.489

Usage (from the repository root, with the app and dev requirements installed):

    python scripts/run_tests.py functional        # offline Python functional tests
    python scripts/run_tests.py js                # Node functional tests
    python scripts/run_tests.py ui                # Playwright UI tests (needs a running app)
    python scripts/run_tests.py all               # functional + js
    python scripts/run_tests.py functional -- -k image   # extra arguments go to pytest

Functional tests run in parallel, one test file per worker, when pytest-xdist
is installed (``pip install pytest-xdist``); otherwise they run serially. A
per-test timeout is applied when pytest-timeout is installed. Neither plugin is
required.

The JavaScript tests use Node's built-in runner. Several load the v2 UI's
TypeScript sources, so ``npm ci`` in ``application/v2_ui`` must have been run
once; the runner reports that instead of failing each test.

See docs/contributing/testing.md for what each suite needs and how tests that
require a live deployment are skipped.
"""

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONAL = REPO_ROOT / "functional_tests"
UI = REPO_ROOT / "ui_tests"
V2_UI = REPO_ROOT / "application" / "v2_ui"
JS_TEST_TIMEOUT_SECONDS = 300


def _has_plugin(module_name):
    return importlib.util.find_spec(module_name) is not None


def run_functional(extra):
    command = [sys.executable, "-m", "pytest", str(FUNCTIONAL), "-p", "no:cacheprovider", "-q"]
    if _has_plugin("xdist"):
        command += ["-n", "auto", "--dist", "loadfile"]
    else:
        print("pytest-xdist is not installed; running serially (this takes a long time).")
    if _has_plugin("pytest_timeout"):
        command += ["--timeout", "300"]
    command += extra
    print("+", " ".join(command), flush=True)
    return subprocess.call(command, cwd=REPO_ROOT)


def run_ui(extra):
    command = [sys.executable, "-m", "pytest", str(UI), "-p", "no:cacheprovider", "-q", *extra]
    print("+", " ".join(command), flush=True)
    return subprocess.call(command, cwd=REPO_ROOT)


def run_js(extra):
    if not (V2_UI / "node_modules").is_dir():
        print(
            "application/v2_ui/node_modules is missing. Run `npm ci` in application/v2_ui first; "
            "several JavaScript tests load the v2 UI's TypeScript sources.",
            file=sys.stderr,
        )
        return 2

    files = sorted([*FUNCTIONAL.glob("test_*.js"), *FUNCTIONAL.glob("test_*.mjs")])
    known = _known_failing_files()
    failed = []
    expected = []
    for path in files:
        # --experimental-vm-modules is needed by tests that evaluate ES modules through
        # node:vm (vm.SourceTextModule); it is harmless for the others.
        command = ["node", "--experimental-vm-modules", "--test", *extra, str(path)]
        try:
            result = subprocess.run(
                command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=JS_TEST_TIMEOUT_SECONDS,
            )
            code, output = result.returncode, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            code, output = 1, f"timed out after {JS_TEST_TIMEOUT_SECONDS}s"
        reason = known.get(path.name)
        if reason and code != 0:
            expected.append(path)
            print(f"xfail  {path.relative_to(REPO_ROOT)} (known failure: {reason})", flush=True)
            continue
        if reason:
            failed.append(path)
            print(f"XPASS  {path.relative_to(REPO_ROOT)} now passes; remove it from "
                  f"functional_tests/known_failures.txt", flush=True)
            continue
        status = "ok" if code == 0 else "FAILED"
        print(f"{status:6} {path.relative_to(REPO_ROOT)}", flush=True)
        if code != 0:
            failed.append(path)
            print(output[-4000:])
    passed = len(files) - len(failed) - len(expected)
    print(f"{passed} of {len(files)} JavaScript test files passed, {len(expected)} known failures, "
          f"{len(failed)} failed.")
    return 1 if failed else 0


def _known_failing_files():
    """Whole-file entries of functional_tests/known_failures.txt (used for JavaScript tests)."""
    if os.environ.get("SIMPLECHAT_IGNORE_KNOWN_FAILURES", "").strip().lower() in ("1", "true", "yes"):
        return {}
    sys.path.insert(0, str(FUNCTIONAL))
    try:
        from test_support.known_failures import LIST_FILE_NAME, parse_known_failures
    finally:
        sys.path.pop(0)
    list_path = FUNCTIONAL / LIST_FILE_NAME
    if not list_path.is_file():
        return {}
    return parse_known_failures(list_path.read_text(encoding="utf-8"))[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the SimpleChat test suites.")
    parser.add_argument("suite", choices=("functional", "js", "ui", "all"))
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="arguments after -- go to pytest or node")
    args = parser.parse_args(argv)
    extra = args.extra[1:] if args.extra[:1] == ["--"] else args.extra
    # Test output can hold characters a Windows console code page cannot print.
    sys.stdout.reconfigure(errors="replace")

    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if args.suite == "functional":
        return run_functional(extra)
    if args.suite == "js":
        return run_js(extra)
    if args.suite == "ui":
        return run_ui(extra)
    functional_code = run_functional(extra)
    js_code = run_js([])
    return functional_code or js_code


if __name__ == "__main__":
    sys.exit(main())
