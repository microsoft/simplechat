#!/usr/bin/env python3
# test_v2_model_catalog_workbench.py
"""
Functional test for the native V2 Model Catalog workbench.
Version: 0.261.253
Implemented in: 0.261.253

V2 used to mount the classic catalog module inside its 768px settings column. It now
draws the catalog natively, and links each connected model to its AI Connection. This
file covers the parts that are structural: V2 no longer depends on the classic module
while the classic page still does, and the click-through is wired from the catalog to
the global connection list only. The behavioural half lives in
``test_v2_model_catalog_logic.ts``, which is bundled and executed here.
"""

import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_ADMIN = V2_DIR / "src" / "components" / "admin"
MANAGER_TSX = V2_ADMIN / "ModelCatalogManager.tsx"
DETAIL_TSX = V2_ADMIN / "ModelCatalogDetail.tsx"
CONNECTIONS_TSX = V2_ADMIN / "ModelConnectionsManager.tsx"
PAGE_TSX = V2_DIR / "src" / "pages" / "AdminSettingsPage.tsx"
STORE_TS = V2_DIR / "src" / "stores" / "modelConnectionsStore.ts"
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_model_catalog_logic.ts"


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_v2_draws_its_own_catalog_and_classic_keeps_the_shared_module():
    """V2 must not pull the classic module back in; classic must keep it."""
    print("Testing the V2 and classic catalog boundary...")
    assert_app_version_at_least("0.261.253")

    for path in (MANAGER_TSX, DETAIL_TSX):
        imports = re.findall(r"^import[^;]*?from\s+'([^']+)'|^import\s+'([^']+)'", _read(path), re.MULTILINE | re.DOTALL)
        specifiers = [left or right for left, right in imports]
        assert specifiers, f"Could not read the imports of {path.name}"
        offending = [spec for spec in specifiers if "model_catalog_ui" in spec or "model-catalog.css" in spec]
        assert not offending, (
            f"{path.name} should render the catalog natively, not import {offending}."
        )
    assert "export function ModelCatalogManager(" in _read(MANAGER_TSX)
    assert "export function CatalogProfilePicker(" in _read(MANAGER_TSX), (
        "AI Connections imports the profile picker from the catalog manager."
    )

    classic_entry = _read(APP_ROOT / "static" / "js" / "admin" / "admin_model_catalog.js")
    assert 'import { mountModelCatalog } from "./model_catalog_ui.js";' in classic_entry, (
        "The classic page still renders its catalog with the shared module."
    )
    assert "css/model-catalog.css" in _read(APP_ROOT / "templates" / "base.html")
    print("  V2 is native; classic still mounts the shared module.")


def test_connected_models_open_their_global_connection():
    """A catalog link opens the exact admin connection, and nothing else answers it."""
    print("\nTesting the connected-model click-through...")
    page = _read(PAGE_TSX)
    assert "onOpenConnection={openConnection}" in page, (
        "The settings page should hand the catalog a way to reach AI Connections."
    )
    assert "requestConnectionFocus(target)" in page
    assert "goToSection('multi-endpoint-configuration')" in page, (
        "Opening a connection has to bring the AI Connections section into view."
    )

    store = _read(STORE_TS)
    assert "focusRequest" in store and "export const requestConnectionFocus" in store

    connections = _read(CONNECTIONS_TSX)
    assert "adapter.scope.kind !== 'admin'" in connections, (
        "Group and personal connection lists must ignore catalog requests; the catalog "
        "only links global connections."
    )
    assert "clearFocus()" in connections, "A request must be consumed once it is answered."
    assert "focusModel={focusModel}" in connections

    detail = _read(DETAIL_TSX)
    assert "connectionId: link.connection_id" in detail, (
        "The link should carry the connection id from the admin catalog response."
    )
    print("  Catalog links reach the admin connection list and its editor.")


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half, skipping when the front-end toolchain is absent."""
    print("\nTesting model catalog logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        print("  skip  application/v2_ui/node_modules is absent; run npm install to include")
        return

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"

    bundle = V2_DIR / "node_modules" / ".cache-model-catalog-check.mjs"
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
        raise AssertionError("the model catalog TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    print(f"  ok  {passed} TypeScript logic checks passed")


if __name__ == "__main__":
    tests = [
        test_v2_draws_its_own_catalog_and_classic_keeps_the_shared_module,
        test_connected_models_open_their_global_connection,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
