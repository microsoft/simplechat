#!/usr/bin/env python3
"""
Functional test for the Admin Settings setup walkthrough targets.
Version: 0.260.018
Implemented in: 0.260.018

The setup walkthrough used to name a tab id for each step. That recorded the
same knowledge twice: the step already knew which setting it was about, and the
tab id was a second copy that went stale the moment a setting moved. After the
information architecture rework, eleven of its twelve steps pointed at tabs that
no longer existed, and the walkthrough would have silently gone nowhere.

Steps now name the card they are about and the owning tab is resolved from the
page. This test ensures every step still points at a card that exists.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.templates import read_admin_settings_template  # noqa: E402

APP_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
)
ADMIN_JS = os.path.join(APP_ROOT, "static", "js", "admin", "admin_settings.js")

CARD_PATTERN = re.compile(r"^\s*(\d+):\s*\{\s*card:\s*'([^']+)'(?:,\s*focus:\s*'([^']+)')?", re.M)


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _walkthrough_targets():
    source = _read(ADMIN_JS)
    start = source.index("const stepToCard = {")
    end = source.index("};", start)
    return CARD_PATTERN.findall(source[start:end])


def test_walkthrough_targets_exist():
    """A step pointing at a missing card sends the walkthrough nowhere."""
    print("Testing setup walkthrough targets exist...")

    markup = read_admin_settings_template()
    targets = _walkthrough_targets()
    assert targets, "Expected the walkthrough step map to be readable"

    missing = []
    for step, card, focus in targets:
        if f'id="{card}"' not in markup:
            missing.append(f"step {step}: card '{card}'")
        if focus and f'id="{focus}"' not in markup:
            missing.append(f"step {step}: focus '{focus}'")

    assert not missing, "Walkthrough steps point at elements that do not exist:\n  " + "\n  ".join(missing)

    print(f"All {len(targets)} walkthrough steps point at elements that exist.")
    return True


def test_walkthrough_does_not_hardcode_tab_ids():
    """Naming a tab id duplicates knowledge that then goes stale."""
    print("Testing the walkthrough resolves tabs from the page...")

    source = _read(ADMIN_JS)
    assert "const stepToTab" not in source, (
        "The walkthrough should not map steps to tab ids. Name the card the "
        "step is about and let openAdminCard find the owning tab, so the map "
        "cannot go stale when a setting moves between tabs."
    )
    assert "window.openAdminCard" in source, (
        "The walkthrough should navigate through openAdminCard, which resolves "
        "the owning tab from the page"
    )

    print("The walkthrough resolves tabs from the page.")
    return True


def test_every_walkthrough_step_is_mapped():
    """A gap in the map silently skips navigation for that step."""
    print("Testing walkthrough step numbering is contiguous...")

    steps = sorted(int(step) for step, _, _ in _walkthrough_targets())
    assert steps, "Expected walkthrough steps"
    expected = list(range(1, len(steps) + 1))
    assert steps == expected, (
        f"Walkthrough steps should be numbered 1..{len(steps)} without gaps, got {steps}"
    )

    print(f"Steps 1..{len(steps)} are all mapped.")
    return True


if __name__ == "__main__":
    tests = [
        test_walkthrough_targets_exist,
        test_walkthrough_does_not_hardcode_tab_ids,
        test_every_walkthrough_step_is_mapped,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
