#!/usr/bin/env python3
"""
Functional test for release notes source and generated page parity.
Version: 0.261.003
Implemented in: 0.261.003

docs/explanation/release_notes.md is the source of truth, and the pages under
docs/explanation/release-notes/ are generated from it by
scripts/build_release_notes_pages.py.

That arrangement hid a data loss. The source was truncated from 46 version
sections to 19, dropping every v0.260 entry and v0.250.229 through v0.250.231,
but the generated pages were not rebuilt. The site kept serving the missing
history, so nothing looked wrong, and the repository sat one routine
regeneration away from erasing roughly 2,400 lines of release notes with no
visible cause.

This test ensures that:

  - Every version documented on a generated page still exists in the source,
    so a truncated source is caught immediately instead of at the next build.
  - Every version in the source appears on a generated page, so stale pages
    are caught before they can mask a later edit.
"""

import io
import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPLANATION_ROOT = REPO_ROOT / "docs" / "explanation"
SOURCE_FILE = EXPLANATION_ROOT / "release_notes.md"
GENERATED_DIR = EXPLANATION_ROOT / "release-notes"

VERSION_HEADING_RE = re.compile(r"^### \*\*\((v[\d.]+)\)\*\*", re.MULTILINE)


def read_text(path):
    """Read a release notes file."""
    return io.open(path, encoding="utf-8", errors="ignore").read()


def versions_in(path):
    """Return the set of release versions documented in a file."""
    return set(VERSION_HEADING_RE.findall(read_text(path)))


def generated_versions():
    """Return every release version documented across the generated pages."""
    found = set()
    for path in sorted(GENERATED_DIR.glob("*.md")):
        found |= versions_in(path)
    return found


def test_generated_pages_match_source():
    """The source file and the generated pages must document the same releases."""
    print("Checking release notes source and generated pages agree...")

    if not SOURCE_FILE.exists():
        print(f"  Missing {SOURCE_FILE.relative_to(REPO_ROOT).as_posix()}.")
        return False

    source = versions_in(SOURCE_FILE)
    generated = generated_versions()

    missing_from_source = sorted(generated - source, reverse=True)
    missing_from_pages = sorted(source - generated, reverse=True)

    if missing_from_source:
        print(f"  {len(missing_from_source)} release(s) are published but no longer "
              f"in the source file:")
        for version in missing_from_source[:30]:
            print(f"    {version}")
        if len(missing_from_source) > 30:
            print(f"    ... and {len(missing_from_source) - 30} more")
        print("  Regenerating would delete these from the site. Restore the "
              "sections in docs/explanation/release_notes.md, then run "
              "scripts/build_release_notes_pages.py.")
        return False

    if missing_from_pages:
        print(f"  {len(missing_from_pages)} release(s) are in the source but not "
              f"on any generated page:")
        for version in missing_from_pages[:30]:
            print(f"    {version}")
        if len(missing_from_pages) > 30:
            print(f"    ... and {len(missing_from_pages) - 30} more")
        print("  The generated pages are stale. Run "
              "scripts/build_release_notes_pages.py and commit the result.")
        return False

    print(f"  {len(source)} releases documented in both the source and the "
          f"generated pages.")
    return True


if __name__ == "__main__":
    assert_app_version_at_least("0.261.003")

    tests = [test_generated_pages_match_source]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test raised an exception: {error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for r in results if r)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
