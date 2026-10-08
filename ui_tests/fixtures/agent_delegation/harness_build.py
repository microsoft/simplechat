# harness_build.py
"""
Build the real Call agent V2 components for deterministic local Playwright tests.
Version: 0.261.093
Implemented in: 0.261.093

Uses the existing V2 esbuild dependency, matching fixtures/orchestration/harness_build.py.
Only HTTP APIs are mocked; React components, state, API helpers and built CSS are real.
"""

import os
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V2 = ROOT / "application" / "v2_ui"
BUNDLE = HERE / "harness.bundle.js"


def ensure_bundle(*, entry=None, bundle=None, api_base=None):
    """Bundle the fixture with the application's existing dependency installation."""
    entry = entry or HERE / "harness_entry.tsx"
    bundle = bundle or BUNDLE
    esbuild = V2 / "node_modules" / "esbuild" / "bin" / "esbuild"
    if not esbuild.exists():
        raise RuntimeError("Run npm ci in application/v2_ui before the V2 browser tests.")
    env = dict(os.environ, NODE_PATH=str(V2 / "node_modules"))
    subprocess.run(
        [
            "node", str(esbuild), str(entry),
            "--bundle", "--format=iife", "--platform=browser", "--jsx=automatic",
            f"--define:import.meta.env={json.dumps({'VITE_API_BASE': api_base} if api_base is not None else {})}",
            '--define:process.env.NODE_ENV="development"',
            f"--outfile={bundle}", "--log-level=warning",
        ],
        cwd=V2,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return bundle
