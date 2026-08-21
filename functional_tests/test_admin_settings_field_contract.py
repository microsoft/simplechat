#!/usr/bin/env python3
# test_admin_settings_field_contract.py
"""
Functional test pinning the Admin Settings form field contract.
Version: 0.260.009
Implemented in: 0.260.009

Admin Settings submits a single form, and the backend reads every value by
field name. That makes the set of `name` attributes the real contract between
the template and `route_frontend_admin_settings.py`. Moving a card between tabs
does not change it; renaming or dropping a `name` silently stops a setting from
saving, with no error anywhere.

The information architecture rework moves most cards between tabs, so this test
holds that contract still:

  1. Every field name recorded in the baseline still exists.
  2. No field name is duplicated except the known radio and checkbox groups,
     which is what stops a mirrored control from submitting a value twice.

New field names are allowed and reported, because adding settings is ordinary
work. Removing or renaming one requires regenerating the baseline in the same
commit:

    python functional_tests/test_admin_settings_field_contract.py --update-baseline

That makes losing a setting a visible, reviewed decision rather than an
accident.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from test_support.templates import read_admin_settings_template
from test_support.versioning import assert_app_version_at_least


BASELINE_PATH = (
    Path(__file__).resolve().parent
    / "test_support"
    / "admin_settings_field_baseline.json"
)

FIELD_RE = re.compile(r'\sname="([^"]+)"')

# Jinja-templated names cannot be compared literally.
TEMPLATED = re.compile(r"\{\{|\{%")


def collect_field_names(markup):
    """Return a Counter of literal form field names in the composed template."""
    return Counter(
        name for name in FIELD_RE.findall(markup) if not TEMPLATED.search(name)
    )


def load_baseline():
    """Read the committed field-name contract."""
    assert BASELINE_PATH.is_file(), (
        f"Missing baseline at {BASELINE_PATH}. Generate it with "
        "--update-baseline."
    )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_no_admin_settings_field_is_lost():
    """A dropped or renamed field name silently stops a setting from saving."""
    print("Testing Admin Settings field name contract...")

    assert_app_version_at_least("0.260.009")
    baseline = load_baseline()
    current = collect_field_names(read_admin_settings_template())

    required = set(baseline["field_names"])
    present = set(current)

    missing = sorted(required - present)
    assert not missing, (
        "These form fields disappeared from Admin Settings, so the settings "
        "they carry can no longer be saved. If a removal is intended, "
        "regenerate the baseline in the same commit with --update-baseline:\n  "
        + "\n  ".join(missing)
    )

    added = sorted(present - required)
    if added:
        print(f"  {len(added)} new field(s) since the baseline: {added[:5]}")

    print(f"All {len(required)} baseline field(s) still present.")


def test_no_unexpected_duplicate_field_names():
    """Two controls sharing a name submit the value twice."""
    print("Testing Admin Settings duplicate field names...")

    baseline = load_baseline()
    current = collect_field_names(read_admin_settings_template())

    allowed = baseline["allowed_duplicates"]
    unexpected = {
        name: count
        for name, count in current.items()
        if count > 1 and name not in allowed
    }

    assert not unexpected, (
        "These field names appear more than once, so the form would submit "
        "each of them multiple times. Mirrored controls must omit the name "
        "attribute rather than repeat it:\n  "
        + "\n  ".join(f"{name} x{count}" for name, count in sorted(unexpected.items()))
    )

    # A group that stops being a group is also a contract change worth noticing.
    shrunk = sorted(
        name for name, count in allowed.items() if current.get(name, 0) < count
    )
    if shrunk:
        print(f"  note: known group(s) now smaller than baseline: {shrunk}")

    print(f"No unexpected duplicates; {len(allowed)} known group(s) intact.")


def update_baseline():
    """Rewrite the baseline from the current template, deliberately."""
    current = collect_field_names(read_admin_settings_template())
    payload = {
        "_comment": (
            "Contract for Admin Settings form field names. Regenerate with "
            "test_admin_settings_field_contract.py --update-baseline only when "
            "a field is intentionally removed or renamed."
        ),
        "field_names": sorted(current),
        "allowed_duplicates": {
            name: count for name, count in sorted(current.items()) if count > 1
        },
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Baseline written: {len(payload['field_names'])} field(s), "
          f"{len(payload['allowed_duplicates'])} known group(s)")


if __name__ == "__main__":
    if "--update-baseline" in sys.argv:
        update_baseline()
        sys.exit(0)

    tests = [
        test_no_admin_settings_field_is_lost,
        test_no_unexpected_duplicate_field_names,
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

    print(f"\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
