#!/usr/bin/env python3
# test_admin_settings_fields_registry_integrity.py
"""
Functional test guarding the shape of the Admin Settings field registry.
Version: 0.261.071
Implemented in: 0.261.071

``ADMIN_SETTINGS_FIELDS`` is a single dict literal that several parallel branches
extend at once, each adding the sections for one admin group. Git merges it
textually, and a dict literal has two properties that make a bad merge silent:

  - A repeated key is not an error. The last one wins and every earlier one
    becomes dead code, so a merge that keeps both sides of a section produces a
    file that imports cleanly and quietly drops settings.
  - A section is just a list, so a merge can keep the key while losing fields
    from one side.

Both have already happened on this branch. ``workflow-settings-section`` was
declared twice with different contents, so the shorter one was dead and a
reordering would have silently dropped six Workflow settings.
``chat-file-uploads-section`` was also declared twice, and there the later
declaration was live and hiding ``enable_chat_file_uploads`` entirely -- a
feature that was invisible in the UI with nothing failing anywhere.

Neither is detectable by importing the module, because by then Python has already
collapsed the duplicates. These checks read the source with ``ast``, which keeps
every key the literal actually contains.
"""

import ast
import sys
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
FIELDS_MODULE = REPO_ROOT / "application" / "single_app" / "admin_settings_fields.py"

fields_module = import_app_module("admin_settings_fields")


def parse_registry():
    """Return ``[(section_id, [field identity, ...]), ...]`` preserving duplicates.

    Deliberately parsed rather than imported: importing collapses duplicate keys,
    which is exactly the defect this test exists to find.
    """
    tree = ast.parse(FIELDS_MODULE.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "ADMIN_SETTINGS_FIELDS"
            for target in node.targets
        ):
            continue

        sections = []
        for key_node, value_node in zip(node.value.keys, node.value.values):
            fields = []
            for entry in value_node.elts:
                literals = {
                    k.value: v.value
                    for k, v in zip(entry.keys, entry.values)
                    if isinstance(v, ast.Constant)
                }
                fields.append(
                    literals.get("key") or f"component:{literals.get('component')}"
                )
            sections.append((key_node.value, fields))
        return sections

    raise AssertionError("ADMIN_SETTINGS_FIELDS not found; the extraction broke.")


def test_no_section_is_declared_twice():
    """A repeated section key silently discards every declaration but the last."""
    print("Testing for duplicate section declarations...")

    assert_app_version_at_least("0.261.071")

    sections = parse_registry()
    counts = Counter(section_id for section_id, _fields in sections)
    duplicates = sorted(key for key, count in counts.items() if count > 1)

    detail = []
    for key in duplicates:
        blocks = [fields for section_id, fields in sections if section_id == key]
        for index, fields in enumerate(blocks, start=1):
            detail.append(f"{key} [{index}/{len(blocks)}]: {fields}")

    assert not duplicates, (
        "These sections are declared more than once in ADMIN_SETTINGS_FIELDS. "
        "Python keeps only the last, so every earlier declaration is dead and its "
        "fields never render. Merge them into one declaration holding every "
        "field:\n  " + "\n  ".join(detail)
    )

    print(f"  All {len(sections)} section declaration(s) are unique.")
    return True


def test_no_field_is_declared_twice_within_a_section():
    """Two entries for one key put two controls on one value."""
    print("\nTesting for duplicate fields inside a section...")

    problems = []
    for section_id, fields in parse_registry():
        counts = Counter(fields)
        for key, count in sorted(counts.items()):
            if count > 1:
                problems.append(f"{section_id}.{key} appears {count} times")

    assert not problems, (
        "These fields are declared more than once inside one section, so two "
        "controls would edit the same value:\n  " + "\n  ".join(problems)
    )

    print("  No section declares the same field twice.")
    return True


def test_every_section_holds_at_least_one_field():
    """An empty section renders as a heading with nothing under it."""
    print("\nTesting that no section is declared empty...")

    empty = [section_id for section_id, fields in parse_registry() if not fields]

    assert not empty, (
        "These sections are declared with no fields, which renders a heading and "
        "nothing else. Remove the declaration or give it the fields it lost in a "
        "merge:\n  " + "\n  ".join(empty)
    )

    print("  Every declared section holds at least one field.")
    return True


def test_the_parsed_registry_matches_the_imported_one():
    """If these disagree, the parse is wrong and the checks above prove nothing."""
    print("\nTesting the parsed registry against the imported module...")

    parsed = {section_id for section_id, _fields in parse_registry()}
    imported = set(fields_module.ADMIN_SETTINGS_FIELDS)

    assert parsed == imported, (
        "The parsed section ids disagree with the imported module, so the ast "
        "extraction no longer reflects the file:\n"
        f"  only parsed:   {sorted(parsed - imported)}\n"
        f"  only imported: {sorted(imported - parsed)}"
    )

    print(f"  Parse and import agree on {len(parsed)} section(s).")
    return True


def test_every_section_id_exists_in_navigation():
    """A section filed under an unknown id has nowhere to render."""
    print("\nTesting section ids against ADMIN_NAV...")

    nav_sections = {
        section["id"]
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
    }

    unknown = sorted(
        {section_id for section_id, _fields in parse_registry()} - nav_sections
    )

    assert not unknown, (
        "These sections are not defined in admin_settings_nav.py, so the V2 UI has "
        "nowhere to render them:\n  " + "\n  ".join(unknown)
    )

    print("  Every declared section exists in ADMIN_NAV.")
    return True


if __name__ == "__main__":
    tests = [
        test_no_section_is_declared_twice,
        test_no_field_is_declared_twice_within_a_section,
        test_every_section_holds_at_least_one_field,
        test_the_parsed_registry_matches_the_imported_one,
        test_every_section_id_exists_in_navigation,
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
