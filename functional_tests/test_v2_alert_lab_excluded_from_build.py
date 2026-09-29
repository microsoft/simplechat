#!/usr/bin/env python3
# test_v2_alert_lab_excluded_from_build.py
"""
Functional test for keeping the V2 workflow alert lab out of production builds.
Version: 0.261.199
Implemented in: 0.261.199

This test ensures the dev-only workflow alert lab (/v2/dev/alert-lab) never ships. App.tsx
registers the lab route only under import.meta.env.DEV, which Vite replaces with false in a
production build, so the minifier drops the route, the lab page and its sample alerts.

The source checks run in every checkout: the lab is reached only through that guarded
route, and the strings used as markers below are unique to the lab, so the build check
cannot pass vacuously. When the SPA has been compiled, the build check searches every
emitted file for those markers.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SOURCE_DIR = REPO_ROOT / "application" / "v2_ui" / "src"
LAB_DIR = V2_SOURCE_DIR / "dev"
APP_FILE = V2_SOURCE_DIR / "App.tsx"
V2_BUILD_DIR = REPO_ROOT / "application" / "single_app" / "static" / "v2"
LAB_ROUTE = "/dev/alert-lab"

# Strings that exist only in lab code, matched case-sensitively, with the file each comes
# from. They are string literals, so a minifier keeps them wherever the code survives.
LAB_MARKERS = {
    "simplechat-dev-alert-lab": "AlertLabPage.tsx",
    "data-dev-lab": "AlertLabPage.tsx",
    "Alert lab": "AlertLabPage.tsx",
    "Hostile text and links": "alertLabSamples.ts",
    LAB_ROUTE: "App.tsx",
}

# Present in every build that contains the workflow alert notice. A bundle without it was
# built before the notice existed, so searching it for the lab would prove nothing.
NOTICE_MARKER = "data-workflow-alert-notice"

TEXT_SUFFIXES = {".html", ".js", ".mjs", ".css", ".map", ".json", ".txt", ".md", ".svg", ""}


def _source_files():
    return [
        path for path in V2_SOURCE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".ts", ".tsx", ".css", ".html"}
    ]


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def test_lab_markers_come_from_the_lab():
    """Each marker is where the lab defines it, and nowhere else in production source."""
    print("Testing workflow alert lab markers are unique to the lab...")
    assert_app_version_at_least("0.261.199")

    assert LAB_DIR.is_dir(), f"The workflow alert lab is missing: {LAB_DIR}"
    for marker, file_name in LAB_MARKERS.items():
        owner = APP_FILE if file_name == "App.tsx" else LAB_DIR / file_name
        assert owner.is_file(), f"{owner} is missing"
        assert marker in _read(owner), (
            f"{owner.relative_to(REPO_ROOT)} no longer contains the lab marker {marker!r}; "
            "update LAB_MARKERS so the build check keeps searching for real lab strings."
        )

    leaks = []
    for path in _source_files():
        if LAB_DIR in path.parents:
            continue
        for number, line in enumerate(_read(path).splitlines(), start=1):
            for marker in LAB_MARKERS:
                if marker not in line:
                    continue
                # App.tsx names the lab route inside the DEV-only expression that registers it.
                if path == APP_FILE and marker == LAB_ROUTE and "import.meta.env.DEV" in line:
                    continue
                leaks.append(f"{path.relative_to(REPO_ROOT)}:{number} contains {marker!r}")

    assert leaks == [], "Lab-only strings found in production source:\n  " + "\n  ".join(leaks)
    print(f"  Checked {len(LAB_MARKERS)} marker(s) against the lab and production source.")
    print("Lab marker test passed!")
    return True


def test_lab_is_reached_only_through_the_dev_route():
    """Only App.tsx imports the lab, and only a DEV-guarded route renders it."""
    print("Testing the workflow alert lab is registered only in development...")

    importers = []
    import_pattern = re.compile(r"""from\s+['"](?:\.{1,2}/)+dev/""")
    for path in _source_files():
        if LAB_DIR in path.parents:
            continue
        if import_pattern.search(_read(path)):
            importers.append(path.relative_to(V2_SOURCE_DIR).as_posix())
    assert importers == ["App.tsx"], f"Only App.tsx may import the lab; found {importers}"

    app_lines = _read(APP_FILE).splitlines()
    route_lines = [line for line in app_lines if f'path="{LAB_ROUTE}"' in line]
    assert len(route_lines) == 1, f"Expected one {LAB_ROUTE} route in App.tsx, found {len(route_lines)}"
    assert re.search(r"import\.meta\.env\.DEV\s*\?", route_lines[0]), (
        f"The {LAB_ROUTE} route must be registered only under import.meta.env.DEV: {route_lines[0].strip()}"
    )

    # Every JSX use of the lab page sits inside that guard.
    usages = [line.strip() for line in app_lines if "<AlertLabPage" in line]
    unguarded = [line for line in usages if "import.meta.env.DEV" not in line]
    assert usages and unguarded == [], f"The lab page is rendered outside the DEV guard: {unguarded}"

    print("  The lab is imported only by App.tsx and rendered only under import.meta.env.DEV.")
    print("Lab route guard test passed!")
    return True


def test_production_bundle_contains_no_lab_code():
    """No emitted file of the compiled SPA contains a lab-only string."""
    print("Testing the compiled V2 bundle for workflow alert lab code...")

    index = V2_BUILD_DIR / "index.html"
    if not index.is_file():
        print(
            "  SKIPPED: the V2 SPA is not compiled in this checkout. "
            "Run 'npm run build' in application/v2_ui to include this check."
        )
        return True

    files = [path for path in V2_BUILD_DIR.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES]
    scripts = [path for path in files if path.suffix.lower() in {".js", ".mjs"}]
    if not any(NOTICE_MARKER in _read(path) for path in scripts):
        print(
            "  SKIPPED: the compiled bundle predates the workflow alert notice. "
            "Rebuild with 'npm run build' in application/v2_ui to include this check."
        )
        return True

    found = []
    for path in files:
        content = _read(path)
        for marker in LAB_MARKERS:
            if marker in content:
                found.append(f"{path.relative_to(REPO_ROOT)} contains {marker!r}")

    assert found == [], "Workflow alert lab code found in the production bundle:\n  " + "\n  ".join(found)
    print(f"  Searched {len(files)} emitted file(s) for {len(LAB_MARKERS)} lab marker(s); none found.")
    print("Production bundle lab exclusion test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_lab_markers_come_from_the_lab,
        test_lab_is_reached_only_through_the_dev_route,
        test_production_bundle_contains_no_lab_code,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except AssertionError as error:
            print(f"Test failed: {error}")
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
