#!/usr/bin/env python3
# test_v2_workflow_change_tracking.py
"""
Functional test for change tracking in the V2 workflow editor.
Version: 0.261.201
Implemented in: 0.261.201

This test ensures the workflow editor tracks every unsaved change against the version it opened:
each change is keyed by a stable ID, so a reorder is one change rather than an edit to every
task; attribution always agrees with the authoring history through undo, redo, coalescing and
eviction; a revert, restore, or AI assist is a new undoable history entry that never deletes a
step or silently discards later work; and an assist candidate can never change enablement, Run
as, identity, or a task approval.

The behaviour lives in TypeScript, so the checks are bundled with esbuild and run under node by
test_v2_workflow_change_tracking_logic.ts, following test_v2_chart_editor.py.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.201"

CHANGE_TRACKING_TS = V2_SRC / "lib" / "workflowChangeTracking.ts"
HISTORY_TS = V2_SRC / "lib" / "workflowAuthoringHistory.ts"
FINGERPRINT_TS = V2_SRC / "lib" / "workflowRunAsFingerprint.ts"
SESSION_TSX = V2_SRC / "components" / "workflows" / "WorkflowAuthoringHistory.tsx"
CHANGE_UI_TSX = V2_SRC / "components" / "workflows" / "WorkflowChangeTracking.tsx"
LOGIC_CHECK = Path(__file__).with_name("test_v2_workflow_change_tracking_logic.ts")

IMPORT_RE = re.compile(r"^\s*import\s[^;]*?from\s+'([^']+)'", re.MULTILINE | re.DOTALL)


def test_version_is_at_least_the_implementing_release():
    """The release that introduced change tracking, or a later one, is configured."""
    assert_app_version_at_least(IMPLEMENTED_IN)
    print("  ok  the configured version includes change tracking")


def test_change_tracking_adds_no_dependency():
    """Diffing is local code: no diff library, no remote asset, nothing outside the app."""
    for path in (CHANGE_TRACKING_TS, HISTORY_TS, FINGERPRINT_TS, SESSION_TSX, CHANGE_UI_TSX):
        source = path.read_text(encoding="utf-8")
        for module in IMPORT_RE.findall(source):
            assert module.startswith(".") or module in {"react", "react-dom"}, (
                f"{path.name} imports {module}; change tracking must stay local code"
            )
        assert "http://" not in source and "https://" not in source, f"{path.name} references a remote URL"
    print("  ok  change tracking imports only local modules and React")


def test_before_and_after_values_render_as_text():
    """Previously and before/after summaries come from user and AI text, so they stay plain text."""
    source = CHANGE_UI_TSX.read_text(encoding="utf-8")
    assert "dangerouslySetInnerHTML" not in source, "a change summary must never be injected as HTML"
    assert "innerHTML" not in source, "a change summary must never be written as HTML"
    print("  ok  change summaries render as plain text")


def test_the_typescript_logic_checks_pass():
    """Run the bundled behaviour checks, when the front-end toolchain is installed."""
    assert LOGIC_CHECK.exists(), "the logic check file is missing"

    if not (V2_DIR / "node_modules").exists():
        print("  --  skipped the TypeScript checks: run npm ci in application/v2_ui")
        return

    bundle = V2_DIR / "node_modules" / ".cache-workflow-change-tracking-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
            timeout=300,
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
            timeout=300,
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 120, f"expected the full check suite, saw {passed} checks"
    print(f"  ok  {passed} TypeScript logic checks passed")


TESTS = [
    test_version_is_at_least_the_implementing_release,
    test_change_tracking_adds_no_dependency,
    test_before_and_after_values_render_as_text,
    test_the_typescript_logic_checks_pass,
]


if __name__ == "__main__":
    passed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
        except Exception as error:  # noqa: BLE001 - report and continue to the next check
            print(f"FAIL  {test.__name__}: {error}")

    print(f"\n{passed}/{len(TESTS)} checks passed")
    sys.exit(0 if passed == len(TESTS) else 1)
