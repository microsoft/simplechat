#!/usr/bin/env python3
# test_v2_alert_lab_excluded_from_build.py
"""
Functional test for keeping the V2 workflow alert lab out of production builds.
Version: 0.261.199
Implemented in: 0.261.199

This test ensures the dev-only workflow alert lab (/v2/dev/alert-lab) never ships.

The exclusion is structural. The lab's only import is the dynamic one in App.tsx,
lazy(() => import('./dev/AlertLabPage')), created only inside an expression guarded by
import.meta.env.DEV. A production build replaces that with false and drops the branch, so
production code never references the lab module and no chunk is emitted for it, even if a
lab file later gains a side effect. No other file may reach src/dev by any route: a static
import or re-export, a bare import, a dynamic import, require(), import.meta.glob, or the
@/ alias.

The source checks run in every checkout, and the strings used as markers are unique to the
lab, so the build check cannot pass vacuously. The build check searches an existing build
of the SPA; it never builds one. Under pytest it is skipped when there is no build, or when
the build predates the workflow alert notice. Run 'npm run build' in application/v2_ui
first to include it.
"""

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = REPO_ROOT / "application" / "v2_ui"
V2_SOURCE_DIR = V2_ROOT / "src"
LAB_DIR = V2_SOURCE_DIR / "dev"
APP_FILE = V2_SOURCE_DIR / "App.tsx"
V2_BUILD_DIR = REPO_ROOT / "application" / "single_app" / "static" / "v2"
LAB_ROUTE = "/dev/alert-lab"
LAB_MODULE = "./dev/AlertLabPage"

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

_QUOTED = r"""(?P<quote>['"`])(?P<spec>[^'"`]+)(?P=quote)"""

# Every way a module can name another one. A dynamic import inside lazy(() => import(...))
# is an ordinary dynamic import here.
SPECIFIER_PATTERNS = {
    "static": re.compile(r"\bfrom\s*" + _QUOTED),
    "bare": re.compile(r"\bimport\s*" + _QUOTED),
    "dynamic": re.compile(r"\bimport\s*\(\s*" + _QUOTED),
    "require": re.compile(r"\brequire\s*\(\s*" + _QUOTED),
}
GLOB_PATTERN = re.compile(r"\bimport\.meta\.glob\w*\s*\((?P<args>[^)]*)\)", re.S)
GLOB_ARGUMENT = re.compile(_QUOTED)

# The one sanctioned reference: the DEV-only lazy loader in App.tsx.
LAB_LOADER = re.compile(
    r"const\s+AlertLabPage\s*=\s*import\.meta\.env\.DEV\s*\?\s*"
    r"lazy\(\s*\(\s*\)\s*=>\s*import\(\s*(['\"])" + re.escape(LAB_MODULE) + r"\1\s*\)"
    r"[^;]*?:\s*null\s*;",
    re.S,
)


def _source_files():
    return [
        path for path in V2_SOURCE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".html"}
    ]


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def _resolve(specifier, importer):
    """Where a specifier points, or None for a package import."""
    specifier = specifier.lstrip("!")
    if specifier.startswith("@/"):
        target = V2_SOURCE_DIR / specifier[2:]
    elif specifier.startswith("/src/"):
        target = V2_ROOT / specifier[1:]
    elif specifier.startswith("."):
        target = importer.parent / specifier
    else:
        return None
    return Path(os.path.normpath(target))


def _is_lab(target):
    return target is not None and (target == LAB_DIR or LAB_DIR in target.parents)


def _references(path, content):
    """Each module reference in a file, as (kind, specifier, offset)."""
    found = []
    for kind, pattern in SPECIFIER_PATTERNS.items():
        for match in pattern.finditer(content):
            found.append((kind, match.group("spec"), match.start()))
    for match in GLOB_PATTERN.finditer(content):
        for argument in GLOB_ARGUMENT.finditer(match.group("args")):
            found.append(("glob", argument.group("spec"), match.start()))
    return found


def _lab_references():
    """Every reference into src/dev from a file outside it."""
    references = []
    for path in _source_files():
        if LAB_DIR in path.parents:
            continue
        content = _read(path)
        for kind, specifier, offset in _references(path, content):
            if _is_lab(_resolve(specifier, path)):
                references.append((path, kind, specifier, offset))
    return references


def test_lab_markers_come_from_the_lab():
    """Each marker is where the lab defines it, and nowhere else in production source."""
    print("Testing workflow alert lab markers are unique to the lab...")
    assert_app_version_at_least("0.261.199")

    assert LAB_DIR.is_dir(), f"The workflow alert lab is missing: {LAB_DIR}"
    for marker, file_name in LAB_MARKERS.items():
        owner = APP_FILE if file_name == "App.tsx" else LAB_DIR / file_name
        assert owner.is_file(), f"{owner} is missing"
        owner_content = _read(owner)
        assert marker in owner_content, (
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


def test_reference_scanner_sees_every_import_form():
    """The scanner used below recognizes each way a file could reach the lab."""
    print("Testing the lab reference scanner against every import form...")

    importer = V2_SOURCE_DIR / "pages" / "Example.tsx"
    samples = {
        "import { AlertLabPage } from '../dev/AlertLabPage';": "static",
        "export { AlertLabPage } from \"../dev/AlertLabPage\";": "static",
        "export * from '@/dev/alertLabSamples';": "static",
        "import '../dev/AlertLabPage';": "bare",
        "const lab = import('../dev/AlertLabPage');": "dynamic",
        "const Lab = lazy(() => import(`../dev/AlertLabPage`));": "dynamic",
        "const Lab = lazy(\n    () => import(\n        '../dev/AlertLabPage'\n    ),\n);": "dynamic",
        "const lab = require('../dev/alertLabSamples');": "require",
        "const pages = import.meta.glob(['./other/*.tsx', '../dev/*.tsx']);": "glob",
        "import lab from '/src/dev/AlertLabPage';": "static",
    }
    for source, kind in samples.items():
        hits = [
            found_kind for found_kind, specifier, _ in _references(importer, source)
            if _is_lab(_resolve(specifier, importer))
        ]
        assert kind in hits, f"The scanner missed a {kind} reference to the lab in: {source!r} (saw {hits})"

    # A dev folder elsewhere, and packages, are not the lab.
    unrelated = [
        "import { x } from './dev/helpers';",
        "import { y } from 'some-package/dev/thing';",
        "const z = import('./devices/Panel');",
    ]
    for source in unrelated:
        hits = [
            specifier for _, specifier, _ in _references(importer, source)
            if _is_lab(_resolve(specifier, importer))
        ]
        assert hits == [], f"The scanner treated {source!r} as a lab reference: {hits}"

    print(f"  The scanner recognized {len(samples)} reference form(s) and ignored {len(unrelated)} unrelated one(s).")
    print("Reference scanner test passed!")
    return True


def test_lab_is_reached_only_through_the_dev_route():
    """The lab's only reference is App.tsx's DEV-only dynamic import, rendered only under DEV."""
    print("Testing the workflow alert lab is registered only in development...")

    references = _lab_references()
    described = [
        f"{path.relative_to(V2_SOURCE_DIR).as_posix()} ({kind} {specifier!r})"
        for path, kind, specifier, _ in references
    ]
    assert len(references) == 1, f"The lab must have exactly one reference, App.tsx's lazy loader; found {described}"
    path, kind, specifier, offset = references[0]
    assert path == APP_FILE and kind == "dynamic" and specifier == LAB_MODULE, (
        f"The lab may be reached only by App.tsx's dynamic import of {LAB_MODULE!r}; found {described}"
    )

    app_content = _read(APP_FILE)
    loaders = list(LAB_LOADER.finditer(app_content))
    assert len(loaders) == 1, (
        "App.tsx must create the lab loader as "
        f"'const AlertLabPage = import.meta.env.DEV ? lazy(() => import('{LAB_MODULE}')...) : null;'"
    )
    loader = loaders[0]
    assert loader.start() <= offset < loader.end(), "The lab's dynamic import sits outside the DEV-only loader"

    app_lines = app_content.splitlines()
    route_lines = [line for line in app_lines if f'path="{LAB_ROUTE}"' in line]
    assert len(route_lines) == 1, f"Expected one {LAB_ROUTE} route in App.tsx, found {len(route_lines)}"
    assert re.search(r"import\.meta\.env\.DEV\s*&&\s*AlertLabPage\s*\?", route_lines[0]), (
        f"The {LAB_ROUTE} route must be registered only under import.meta.env.DEV: {route_lines[0].strip()}"
    )

    # Every JSX use of the lab page sits inside that guard.
    usages = [line.strip() for line in app_lines if "<AlertLabPage" in line]
    unguarded = [line for line in usages if "import.meta.env.DEV" not in line]
    assert usages and unguarded == [], f"The lab page is rendered outside the DEV guard: {unguarded}"

    print("  The lab's only reference is App.tsx's DEV-only lazy import, rendered only under import.meta.env.DEV.")
    print("Lab route guard test passed!")
    return True


def test_production_bundle_contains_no_lab_code():
    """No emitted file of an existing production build is, or contains, lab code."""
    print("Testing the compiled V2 bundle for workflow alert lab code...")

    index = V2_BUILD_DIR / "index.html"
    if not index.is_file():
        pytest.skip(
            "The V2 SPA is not compiled in this checkout. "
            "Run 'npm run build' in application/v2_ui to include this check."
        )

    emitted = [path for path in V2_BUILD_DIR.rglob("*") if path.is_file()]
    files = [path for path in emitted if path.suffix.lower() in TEXT_SUFFIXES]
    scripts = [path for path in files if path.suffix.lower() in {".js", ".mjs"}]
    has_notice = any(NOTICE_MARKER in _read(path) for path in scripts)
    if not has_notice:
        pytest.skip(
            "The compiled bundle predates the workflow alert notice. "
            "Rebuild with 'npm run build' in application/v2_ui to include this check."
        )

    # A lab chunk would be named after its module, for example assets/AlertLabPage-<hash>.js.
    lab_named = [
        path.relative_to(REPO_ROOT).as_posix() for path in emitted
        if "alertlab" in path.name.lower().replace("-", "").replace("_", "")
    ]
    assert lab_named == [], f"The production build emitted lab files: {lab_named}"

    found = []
    for path in files:
        content = _read(path)
        for marker in LAB_MARKERS:
            if marker in content:
                found.append(f"{path.relative_to(REPO_ROOT)} contains {marker!r}")

    assert found == [], "Workflow alert lab code found in the production bundle:\n  " + "\n  ".join(found)
    print(
        f"  The build emitted {len(emitted)} file(s), none named for the lab; searched the "
        f"{len(files)} text file(s) for {len(LAB_MARKERS)} lab marker(s) and found none."
    )
    print("Production bundle lab exclusion test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_lab_markers_come_from_the_lab,
        test_reference_scanner_sees_every_import_form,
        test_lab_is_reached_only_through_the_dev_route,
        test_production_bundle_contains_no_lab_code,
    ]
    results = []
    skipped = 0
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except pytest.skip.Exception as skip:
            print(f"  SKIPPED: {skip}")
            skipped += 1
            results.append(True)
        except AssertionError as error:
            print(f"Test failed: {error}")
            results.append(False)
    print(f"\nResults: {sum(results) - skipped}/{len(results)} tests passed, {skipped} skipped")
    sys.exit(0 if all(results) else 1)
