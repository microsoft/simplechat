#!/usr/bin/env python3
# test_v2_admin_help_logic.py
"""
Functional test runner for the V2 Admin Settings Help group logic.
Version: 0.261.275
Implemented in: 0.261.275

The Help group's behavioural rules live in TypeScript: which announcements are
shared when the stored map is incomplete, where an admin shortcut lands, which
URLs may reach an href or a mailto: draft, and what the publication notice says
in each Support state. ``test_v2_admin_help_logic.ts`` executes them, together
with static renders of the new cards; this file bundles it with the esbuild that
Vite already brings in and runs it under node.

The run is skipped when ``application/v2_ui/node_modules`` is absent, as the other
V2 logic runners are, so a Python-only environment still runs the rest of the
suite.
"""

import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_admin_help_logic.ts"


def test_help_logic_checks_pass():
    """Execute the TypeScript checks, skipping when the front-end toolchain is absent."""
    print("Testing Help group logic (TypeScript)...")

    assert_app_version_at_least("0.261.275")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript Help logic checks are missing"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-admin-help-check.mjs"
    try:
        subprocess.run(
            [
                "npx",
                "esbuild",
                str(LOGIC_CHECK_TS),
                "--bundle",
                "--platform=node",
                "--format=esm",
                "--packages=external",
                # apiClient reads import.meta.env, which only Vite provides.
                "--define:import.meta.env={}",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            cwd=str(V2_DIR),
            check=True,
            shell=(sys.platform == "win32"),
        )
        result = subprocess.run(
            ["node", str(bundle)],
            cwd=str(V2_DIR),
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32"),
        )
    finally:
        if bundle.exists():
            bundle.unlink()

    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError("the TypeScript Help logic checks failed")

    passed = result.stdout.count("  ok  ")
    assert passed >= 15, f"Only {passed} Help logic checks ran; the runner likely broke."
    print(f"  ok  {passed} TypeScript Help logic checks passed")
    return True


if __name__ == "__main__":
    try:
        success = bool(test_help_logic_checks_pass())
    except Exception as exc:
        print(f"FAILED test_help_logic_checks_pass: {exc}")
        success = False
    sys.exit(0 if success else 1)
