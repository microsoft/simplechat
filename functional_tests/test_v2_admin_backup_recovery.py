#!/usr/bin/env python3
# test_v2_admin_backup_recovery.py
"""
Functional test for the V2 Admin Settings Backup & Recovery surface.
Version: 0.261.275
Implemented in: 0.261.275

The V2 admin page used to show Backup & Recovery as an empty category. It now renders
one card per navigation section, backed by the classic data-management API, and its
settings save through the page's Save bar after the main settings.

The Python checks here are structural: that the page routes every Backup & Recovery
component, saves main settings before the separate data-management document, counts
both in the Save bar, guards in-app navigation, and that the new code uses no unsafe
HTML sinks. The behavioural half -- the save payload, unsaved-edit detection, review
staleness, step gates, typed confirmations, paging and the store's save-first rules --
is executed by the companion TypeScript checks this file bundles and runs.
"""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = REPO_ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
PAGE_TSX = V2_SRC / "pages" / "AdminSettingsPage.tsx"
DM_COMPONENTS = V2_SRC / "components" / "admin" / "dataManagement"
DM_LIB_FILES = (
    V2_SRC / "lib" / "dataManagement.ts",
    V2_SRC / "lib" / "dataManagementLogic.ts",
    V2_SRC / "lib" / "dataManagementFields.ts",
    V2_SRC / "stores" / "dataManagementStore.ts",
)
LOGIC_CHECK_TS = Path(__file__).resolve().parent / "test_v2_admin_backup_recovery_logic.ts"

DM_COMPONENT_NAMES = (
    "data-management-readiness",
    "data-management-backup-runs",
    "data-management-schedule",
    "data-management-storage",
    "data-management-encryption",
    "data-management-migration",
    "data-management-backup-inventory",
    "data-management-cosmos-editor",
    "data-management-jobs",
)

fields_module = import_app_module("admin_settings_fields")


def _read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_every_backup_component_is_declared_and_routed():
    """A declared card with no renderer branch would leave the category empty again."""
    print("Testing Backup & Recovery component declarations and routing...")

    assert_app_version_at_least("0.261.275")

    declared = {
        field.get("component"): section_id
        for section_id, field in fields_module.iter_fields()
        if field.get("type") == "component"
        and str(field.get("component", "")).startswith("data-management-")
    }
    assert set(declared) == set(DM_COMPONENT_NAMES), (
        "The Backup & Recovery components declared in admin_settings_fields.py changed: "
        f"{sorted(declared)}"
    )

    page = _read(PAGE_TSX)
    missing = [name for name in DM_COMPONENT_NAMES if f"case '{name}':" not in page]
    assert not missing, f"AdminSettingsPage.tsx has no branch for: {missing}"

    for field_section, field in (
        (section_id, field)
        for section_id, field in fields_module.iter_fields()
        if field.get("component") in DM_COMPONENT_NAMES
    ):
        keywords = field.get("keywords")
        assert isinstance(keywords, list) and keywords, (
            f"{field_section} should carry search keywords; a component has one label and "
            "the page search would otherwise miss what the card contains."
        )

    print(f"  All {len(DM_COMPONENT_NAMES)} components are declared, searchable and routed.")
    return True


def test_the_save_bar_saves_main_settings_before_backup_settings():
    """Backup storage is validated against the saved Enhanced Citations settings."""
    print("\nTesting the page's save coordinator...")

    page = _read(PAGE_TSX)

    assert "dirtyCount={dirtyKeys.length + dmDirtyCount}" in page, (
        "The Save bar should count unsaved Backup & Recovery settings with the main ones."
    )
    assert "useDataManagementStore.getState().discard()" in page, (
        "Discard should also discard unsaved Backup & Recovery settings."
    )

    save_body = page[page.index("const save = useCallback(async () => {"):]
    save_body = save_body[: save_body.index("}, [draft, refreshBootstrap]);")]
    main_index = save_body.find("api.patch<AdminSettingsPatchResponse>")
    dm_index = save_body.find("useDataManagementStore.getState().save()")
    assert main_index != -1 and dm_index != -1, "The save coordinator lost one of its phases."
    assert main_index < dm_index, (
        "Main settings must be saved before Backup & Recovery settings, because the "
        "data-management save validates against the saved Enhanced Citations storage."
    )
    assert "return false;" in save_body[main_index:dm_index], (
        "A failed main save should stop before saving Backup & Recovery settings."
    )
    assert "useDataManagementStore.getState().setMainDirtyKeys([]);" in save_body[main_index:dm_index], (
        "A successful main save must clear the unsaved main keys before it resolves: an "
        "action waiting on Save all checks them again straight away, before React re-renders."
    )

    assert "registerSaveAll(save)" in page and "setMainDirtyKeys(dirtyKeys)" in page, (
        "The cards need the page's save coordinator and the unsaved main keys for the "
        "save-first guard."
    )
    assert "useBlocker(" in page, (
        "In-app navigation away from unsaved changes should ask first; the Save bar's "
        "unload prompt only covers closing the tab."
    )
    assert page.count("useBlocker(") == 1, (
        "A router honours one blocker at a time and silently ignores the others, so the "
        "page must guard every way out with a single useBlocker."
    )
    assert "useDataManagementStore.getState().reset()" in page, (
        "Leaving the page should reset the Backup & Recovery store, as the main draft is."
    )

    print("  Main settings save first, both drafts count, and leaving is guarded.")
    return True


def test_backup_recovery_code_uses_no_html_sinks():
    """Server text is rendered as text; download links are built from a literal prefix."""
    print("\nTesting Backup & Recovery code for unsafe sinks...")

    files = sorted(DM_COMPONENTS.rglob("*.tsx")) + list(DM_LIB_FILES)
    assert len(files) >= 10, f"Expected the Backup & Recovery files, found {len(files)}"

    forbidden = re.compile(
        r"dangerouslySetInnerHTML|\.innerHTML|outerHTML|insertAdjacentHTML|javascript:"
        r"|(https?:)?//(cdn|unpkg|jsdelivr|cdnjs)",
        re.IGNORECASE,
    )
    offenders = []
    for path in files:
        for line_number, line in enumerate(_read(path).splitlines(), start=1):
            if forbidden.search(line):
                offenders.append(f"{path.relative_to(V2_SRC)}:{line_number}: {line.strip()[:100]}")
    assert not offenders, "Unsafe sinks in Backup & Recovery code:\n  " + "\n  ".join(offenders)

    href_values = []
    for path in sorted(DM_COMPONENTS.rglob("*.tsx")):
        href_values.extend(re.findall(r"href=\{([^}]*)\}", _read(path)))
    unsafe = [value for value in href_values if "migrationManifestUrl(" not in value]
    assert not unsafe, (
        "Backup & Recovery links must come from migrationManifestUrl(), which builds a "
        f"same-origin path from a literal prefix and an encoded id: {unsafe}"
    )

    # The repository's XSS sink checker approves the builder by name, so its shape is
    # pinned here: a literal API prefix, an encoded job id and a literal, encoded query.
    lib = _read(V2_SRC / "lib" / "dataManagement.ts")
    assert "export const DM_API = '/api/admin/data-management';" in lib
    builder = lib[lib.index("export function migrationManifestUrl("):]
    builder = builder[: builder.index("\n}\n")]
    assert "apiUrl(`${DM_API}/jobs/${encodeURIComponent(jobId)}/migration-manifest${query}`)" in builder, (
        "migrationManifestUrl must stay a same-origin path with an encoded job id"
    )
    assert "`?statuses=${encodeURIComponent(MANIFEST_FAILURE_STATUSES)}`" in builder
    spec = importlib.util.spec_from_file_location("check_xss_sinks", REPO_ROOT / "scripts" / "check_xss_sinks.py")
    assert spec is not None and spec.loader is not None, "Expected a module spec for check_xss_sinks.py"
    checker = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    # Registered while it runs, because the checker's dataclasses look their module up.
    sys.modules[spec.name] = checker
    try:
        spec.loader.exec_module(checker)
        approved = "migrationManifestUrl" in checker.TS_SAME_ORIGIN_URL_BUILDERS
        # Run the checker over every Backup & Recovery source file, as CI does.
        issues = []
        for path in files:
            issues.extend(checker.format_error_annotation(issue) for issue in checker.inspect_file(path))
    finally:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
    assert approved, "The XSS sink checker should list migrationManifestUrl as a reviewed same-origin URL builder"
    assert not issues, "The XSS sink checker reports Backup & Recovery issues:\n  " + "\n  ".join(issues)

    print(f"  {len(files)} file(s) clean; {len(href_values)} dynamic link(s) all built safely.")
    return True


def test_the_typescript_logic_checks_pass():
    """Execute the behavioural half; a missing front-end toolchain is a visible skip."""
    print("\nTesting Backup & Recovery logic (TypeScript)...")

    if not (V2_DIR / "node_modules").exists():
        reason = "application/v2_ui/node_modules is absent; run npm ci there to include these checks"
        if os.environ.get("PYTEST_CURRENT_TEST"):
            import pytest

            pytest.skip(reason)
        print(f"  skip  {reason}")
        return True

    assert LOGIC_CHECK_TS.exists(), "The TypeScript logic checks are missing"
    declared = len(re.findall(r"^check\(", LOGIC_CHECK_TS.read_text(encoding="utf-8"), re.MULTILINE))
    assert declared >= 38, f"expected the logic check file to declare its checks, found {declared}"

    # functional_tests/ has no node_modules of its own, so the bundle is written where
    # node can resolve bare imports from.
    bundle = V2_DIR / "node_modules" / ".cache-admin-backup-recovery-check.mjs"
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
        raise AssertionError("the Backup & Recovery TypeScript logic checks failed")

    passed = result.stdout.count("  ok  ")
    if passed != declared:
        print(result.stdout)
        raise AssertionError(f"{passed} of {declared} declared TypeScript logic checks reported ok")
    print(f"  ok  {passed} TypeScript logic checks passed")
    return True


if __name__ == "__main__":
    tests = [
        test_every_backup_component_is_declared_and_routed,
        test_the_save_bar_saves_main_settings_before_backup_settings,
        test_backup_recovery_code_uses_no_html_sinks,
        test_the_typescript_logic_checks_pass,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
