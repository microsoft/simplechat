#!/usr/bin/env python3
"""
Functional test for Admin Settings modal placement across tab panes.
Version: 0.260.014
Implemented in: 0.260.014

Admin Settings modals are interleaved between cards rather than collected at the
end of the template, so splitting a tab pane can silently strand a modal in a
pane that never opens it. A modal inside an inactive tab pane cannot be shown,
because the pane itself is hidden, so the failure is invisible until a user
clicks the button.

This test ensures every modal lives in a pane that can actually open it.
"""

import os
import re
import sys
import collections

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

PANES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
    "templates",
    "admin",
    "_panes",
)
SHELL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
    "templates",
    "admin_settings.html",
)

MODAL_PATTERN = re.compile(r'class="modal fade[^"]*"\s+id="([^"]+)"')
TRIGGER_PATTERN = re.compile(r'data-bs-target="#([^"]+)"')

# The shell sits outside every pane, so a modal there is reachable from anywhere
# and a trigger there is not owned by any one pane.
SHELL_KEY = "__shell__"


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _collect():
    """Map each modal id to its pane, and each modal id to the panes opening it."""
    modal_home = {}
    trigger_homes = collections.defaultdict(set)

    sources = [(SHELL_KEY, SHELL)]
    for name in sorted(os.listdir(PANES_DIR)):
        if name.endswith(".html"):
            sources.append((name[: -len(".html")], os.path.join(PANES_DIR, name)))

    for pane, path in sources:
        markup = _read(path)
        for match in MODAL_PATTERN.finditer(markup):
            modal_home[match.group(1)] = pane
        for match in TRIGGER_PATTERN.finditer(markup):
            trigger_homes[match.group(1)].add(pane)

    return modal_home, trigger_homes


def test_modals_live_where_they_are_opened():
    """Every modal must sit in a pane that can open it, or in the shell."""
    print("Testing Admin Settings modal placement...")

    modal_home, trigger_homes = _collect()
    assert modal_home, "No modals found; the collector is probably looking in the wrong place"

    stranded = []
    for modal_id, home in sorted(modal_home.items()):
        if home == SHELL_KEY:
            continue
        openers = trigger_homes.get(modal_id)
        if not openers:
            # Opened from JavaScript rather than markup, which this test cannot
            # attribute to a pane. Those are covered by the card link tests.
            continue
        foreign = {pane for pane in openers if pane not in (home, SHELL_KEY)}
        if foreign and home not in openers:
            stranded.append((modal_id, home, sorted(foreign)))

    assert not stranded, "Modals stranded in a pane that never opens them:\n" + "\n".join(
        f"  '{modal_id}' lives in '{home}' but is only opened from {openers}"
        for modal_id, home, openers in stranded
    )

    print(f"All {len(modal_home)} modals sit in a pane that can open them.")
    return True


def test_modal_ids_are_unique():
    """A duplicated modal id would make the wrong dialog open."""
    print("Testing Admin Settings modal id uniqueness...")

    counts = collections.Counter()
    paths = [SHELL] + [
        os.path.join(PANES_DIR, name)
        for name in sorted(os.listdir(PANES_DIR))
        if name.endswith(".html")
    ]
    for path in paths:
        for match in MODAL_PATTERN.finditer(_read(path)):
            counts[match.group(1)] += 1

    duplicates = sorted(modal_id for modal_id, count in counts.items() if count > 1)
    assert not duplicates, f"Modal ids declared more than once: {duplicates}"

    print(f"All {len(counts)} modal ids are unique.")
    return True


if __name__ == "__main__":
    tests = [
        test_modals_live_where_they_are_opened,
        test_modal_ids_are_unique,
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
