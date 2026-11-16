# test_v2_agents_catalog.py
"""
Functional tests for native V2 catalogue logic and route wiring.
Version: 0.261.305
Implemented in: 0.261.305

Execute the real TypeScript helpers and shared Chat controls through Vite's
existing esbuild dependency. No browser or Azure service is needed. The separate
UI suite exercises the production SPA, interactions, and refreshed chat launch.
"""

import subprocess
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
V2_DIR = ROOT / "application" / "v2_ui"
SRC = V2_DIR / "src"
LOGIC_TEST = Path(__file__).with_name("test_v2_agents_catalog_logic.ts")


def test_native_catalogue_wiring():
    """The SPA and Latest Features use the native catalogue, not a legacy hand-off."""
    assert_app_version_at_least("0.261.305")
    app = (SRC / "App.tsx").read_text(encoding="utf-8")
    assert '<Route path="/agents" element={<AgentsCatalogPage />} />' in app
    assert "PlaceholderPage" not in app
    assert not (SRC / "pages" / "PlaceholderPage.tsx").exists()
    shortcut = (SRC / "lib" / "latestFeatureShortcuts.ts").read_text(encoding="utf-8")
    assert "case '/agents':" in shortcut
    assert "return route(AGENTS_PATH);" in shortcut
    return True


def test_catalogue_logic():
    """Run ranking, filtering, display parsing, and scope-aware Chat checks."""
    esbuild = V2_DIR / "node_modules" / ".bin" / (
        "esbuild.cmd" if sys.platform == "win32" else "esbuild"
    )
    if not esbuild.is_file():
        raise AssertionError("The V2 toolchain is missing; run npm ci in application/v2_ui.")
    bundle = V2_DIR / "node_modules" / ".cache-agents-catalog-check.mjs"
    try:
        subprocess.run(
            [
                str(esbuild), str(LOGIC_TEST), "--bundle", "--platform=node",
                "--format=esm", "--packages=external", "--define:import.meta.env={}",
                f"--outfile={bundle}", "--log-level=error",
            ],
            cwd=V2_DIR,
            check=True,
        )
        result = subprocess.run(
            ["node", str(bundle)], cwd=V2_DIR, capture_output=True, text=True,
            check=False,
        )
    finally:
        bundle.unlink(missing_ok=True)
    if result.returncode:
        raise AssertionError(f"Catalogue checks failed:\n{result.stdout}\n{result.stderr}")
    passed = result.stdout.count("  ok  ")
    assert passed >= 28, f"Only {passed} catalogue checks ran."
    print(f"{passed} catalogue logic checks passed.")
    return True


if __name__ == "__main__":
    success = True
    for test in (test_native_catalogue_wiring, test_catalogue_logic):
        try:
            test()
        except Exception as exc:
            success = False
            print(f"FAILED {test.__name__}: {exc}")
    sys.exit(0 if success else 1)
