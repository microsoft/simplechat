#!/usr/bin/env python3
"""
Functional test for control center GroupManager refreshGroups duplicate fix.
Version: 0.239.145
Implemented in: 0.239.145

This test ensures that the GroupManager object in control_center.html defines
refreshGroups only once so object literal members are not accidentally
overwritten.
"""

# test_control_center_group_manager_refresh_groups_duplicate_fix.py

from pathlib import Path
import re
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT_DIR / "application" / "single_app" / "templates" / "control_center.html"


def test_refresh_groups_defined_once() -> bool:
    """Validate GroupManager.refreshGroups is declared exactly once."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    matches = re.findall(r"\brefreshGroups\s*:\s*function\s*\(", template)

    if len(matches) != 1:
        print(f"Expected exactly 1 refreshGroups definition, found {len(matches)}")
        return False

    if "Loading groups..." not in template:
        print("Expected refreshGroups implementation to preserve the loading placeholder")
        return False

    print("refreshGroups is defined exactly once and preserves the loading state")
    return True


if __name__ == "__main__":
    success = test_refresh_groups_defined_once()
    sys.exit(0 if success else 1)