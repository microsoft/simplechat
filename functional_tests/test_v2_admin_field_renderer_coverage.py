#!/usr/bin/env python3
# test_v2_admin_field_renderer_coverage.py
"""
Functional test that the V2 admin UI renders every field the schema can declare.
Version: 0.261.038
Implemented in: 0.261.038

The V2 admin surface is driven by ``admin_settings_fields.py``. That indirection has one
silent failure mode: the schema can declare a field type, or name a bespoke component,
that the React renderer has no branch for. Nothing raises. The control simply does not
appear, and the setting becomes invisible again -- the exact problem the schema was added
to solve.

These checks read the schema from Python and the branches from the TypeScript, and require
them to agree.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
FIELDS_TSX = V2_SRC / "components" / "admin" / "fields.tsx"
PAGE_TSX = V2_SRC / "pages" / "AdminSettingsPage.tsx"
ADMIN_COMPONENTS_DIR = V2_SRC / "components" / "admin"

fields_module = import_app_module("admin_settings_fields")


def read(path):
    assert path.is_file(), f"Missing expected V2 source file: {path}"
    return path.read_text(encoding="utf-8")


def test_every_field_type_has_a_renderer():
    """A declared type with no branch renders nothing at all."""
    print("Testing renderer coverage for every field type...")

    assert_app_version_at_least("0.261.038")

    controls = read(FIELDS_TSX)
    page = read(PAGE_TSX)

    unhandled = []
    for field_type in fields_module.FIELD_TYPES:
        in_controls = f"case '{field_type}':" in controls
        # The page owns the types that need an API of their own.
        in_page = f"field.type === '{field_type}'" in page
        if not in_controls and not in_page:
            unhandled.append(field_type)

    assert not unhandled, (
        "These field types can be declared in admin_settings_fields.py but the V2 UI has "
        "no branch for them, so a field using one would silently not render. Add a case "
        "to components/admin/fields.tsx or a branch to pages/AdminSettingsPage.tsx:\n  "
        + "\n  ".join(unhandled)
    )

    print(f"  All {len(fields_module.FIELD_TYPES)} field type(s) have a renderer.")
    return True


def test_every_declared_component_has_a_branch():
    """A component field naming an unimplemented widget renders nothing."""
    print("\nTesting renderer coverage for bespoke components...")

    page = read(PAGE_TSX)

    declared = sorted(
        {
            field["component"]
            for _section_id, field in fields_module.iter_fields()
            if field.get("type") == "component" and field.get("component")
        }
    )
    assert declared, "No component fields found; the schema extraction likely broke."

    missing = [name for name in declared if f"case '{name}':" not in page]

    assert not missing, (
        "These components are named by the schema but have no branch in "
        "AdminSettingsPage.tsx, so their section would render an empty space:\n  "
        + "\n  ".join(missing)
    )

    print(f"  All {len(declared)} declared component(s) have a branch.")
    return True


def test_renderer_does_not_claim_unknown_components():
    """A branch for a component nobody declares is dead code that hides a typo."""
    print("\nTesting for renderer branches without a schema entry...")

    page = read(PAGE_TSX)
    declared = {
        field["component"]
        for _section_id, field in fields_module.iter_fields()
        if field.get("type") == "component" and field.get("component")
    }

    # Component names are kebab-case; field types are snake_case, so the two cannot
    # be confused by this pattern.
    branch_names = set(re.findall(r"case '([a-z]+(?:-[a-z]+)+)':", page))
    orphaned = sorted(branch_names - declared)

    assert not orphaned, (
        "These component branches exist in the UI but no schema field asks for them. "
        "Either the schema entry was removed or the name is misspelled:\n  "
        + "\n  ".join(orphaned)
    )

    print("  No orphaned component branches.")
    return True


def test_admin_components_use_no_remote_assets():
    """Browser JavaScript must be served from local static assets only."""
    print("\nTesting that admin components load no remote assets...")

    forbidden = re.compile(
        r"""(https?:)?//(cdn|unpkg|jsdelivr|cdnjs|ajax\.googleapis|fonts\.googleapis)""",
        re.IGNORECASE,
    )

    offenders = []
    for path in sorted(ADMIN_COMPONENTS_DIR.glob("*.tsx")):
        content = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), start=1):
            if forbidden.search(line):
                offenders.append(f"{path.name}:{line_number}: {line.strip()[:100]}")

    assert not offenders, (
        "These admin components reference a remote asset. Browser assets must be "
        "vendored locally under static/:\n  " + "\n  ".join(offenders)
    )

    checked = len(list(ADMIN_COMPONENTS_DIR.glob("*.tsx")))
    print(f"  {checked} admin component file(s) reference only local assets.")
    return True


if __name__ == "__main__":
    tests = [
        test_every_field_type_has_a_renderer,
        test_every_declared_component_has_a_branch,
        test_renderer_does_not_claim_unknown_components,
        test_admin_components_use_no_remote_assets,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
