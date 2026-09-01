#!/usr/bin/env python3
"""
Functional test for V2 composer dropdown placement.
Version: 0.261.011
Implemented in: 0.261.011

The V2 composer is anchored to the bottom of the viewport, so its Model, Agent,
Prompt and Reasoning pickers had no room beneath them. The menu was positioned
with a fixed downward offset, which put the options below the bottom edge of the
window where they could not be reached or even seen.

This test ensures the shared Dropdown measures the space around its trigger and
flips above it when there is not enough room below, and that it clamps its own
height to the space actually available so it can never overflow either edge.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROPDOWN = os.path.join(
    REPO_ROOT, "application", "v2_ui", "src", "components", "ui", "Dropdown.tsx"
)
COMPOSER = os.path.join(
    REPO_ROOT, "application", "v2_ui", "src", "components", "chat", "Composer.tsx"
)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_menu_is_not_pinned_below_the_trigger():
    """The menu must be able to render above the trigger."""
    print("Testing that the menu can open upward...")
    try:
        source = read(DROPDOWN)

        assert "bottom-full" in source, (
            "Dropdown never positions its menu above the trigger, so a picker at the "
            "bottom of the viewport still renders off-screen."
        )
        assert "top-full" in source, (
            "The downward placement should be stated explicitly rather than relying on "
            "static flow position, so both branches are readable."
        )

        # The old behaviour was an unconditional downward offset.
        unconditional = re.search(r"absolute[^'\"]*\bmt-2\b[^'\"]*max-h-80", source)
        assert not unconditional, (
            "The menu still carries an unconditional downward offset and fixed height."
        )

        print("Upward placement test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_placement_is_measured_from_available_space():
    """Placement must come from the trigger's position, not a hardcoded direction."""
    print("Testing that placement is measured...")
    try:
        source = read(DROPDOWN)

        assert "getBoundingClientRect" in source, (
            "Placement is not measured from the trigger's position."
        )
        assert "window.innerHeight" in source, (
            "Space below the trigger is not compared against the viewport height."
        )

        for name in ("spaceBelow", "spaceAbove"):
            assert name in source, f"Expected {name} to be considered when placing the menu."

        # Down must remain the preference when there is room, otherwise this is just a
        # hardcoded flip that would break a Dropdown used near the top of a page.
        assert re.search(
            r"if\s*\(\s*spaceBelow\s*>=\s*MENU_MAX_HEIGHT\s*\|\|\s*spaceBelow\s*>=\s*spaceAbove\s*\)",
            source,
        ), "Downward placement should still win whenever there is room below."

        print("Measurement test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_height_is_clamped_to_available_space():
    """A menu taller than the space available must scroll rather than overflow."""
    print("Testing that the menu height is clamped...")
    try:
        source = read(DROPDOWN)

        assert "maxHeight" in source, "The menu does not constrain its own height."
        assert "style={{ maxHeight }}" in source, (
            "The measured height is never applied to the menu element."
        )
        assert "overflow-y-auto" in source, (
            "A clamped menu must scroll, or options become unreachable."
        )
        assert "MIN_USABLE_HEIGHT" in source, (
            "Without a floor, a cramped viewport could collapse the menu to nothing."
        )

        print("Height clamp test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_placement_follows_the_trigger_while_open():
    """Resizing or scrolling must not strand an open menu off-screen."""
    print("Testing that placement is re-evaluated while open...")
    try:
        source = read(DROPDOWN)

        assert "addEventListener('resize', measure)" in source, (
            "Resizing the window does not re-evaluate placement."
        )
        assert "addEventListener('scroll', measure, true)" in source, (
            "Scrolling does not re-evaluate placement. The capture flag matters, "
            "because the composer's ancestors scroll, not just the page."
        )
        assert "removeEventListener('resize', measure)" in source, (
            "The resize listener is never removed."
        )
        assert "removeEventListener('scroll', measure, true)" in source, (
            "The scroll listener is never removed."
        )

        print("Re-evaluation test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_all_composer_pickers_share_the_fixed_component():
    """The fix is only complete if every bottom-anchored picker uses this component."""
    print("Testing that composer pickers use the shared Dropdown...")
    try:
        composer = read(COMPOSER)

        usages = composer.count("<Dropdown")
        assert usages >= 4, (
            f"Expected the model, agent, prompt and reasoning pickers to use Dropdown, "
            f"found {usages} usages."
        )

        # A picker that rolled its own popover would not get the fix.
        assert 'placeholder="Reasoning"' in composer, (
            "The reasoning picker is no longer a Dropdown, so it would not be fixed."
        )
        assert "absolute" not in composer, (
            "Composer defines its own absolutely positioned popover, which would not "
            "benefit from the shared placement logic."
        )

        print("Shared component test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_is_at_least_implementation_version():
    """The fix must be present in at least the version that introduced it."""
    print("Testing application version...")
    try:
        assert_app_version_at_least("0.261.011")
        print("Application version test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_menu_is_not_pinned_below_the_trigger,
        test_placement_is_measured_from_available_space,
        test_height_is_clamped_to_available_space,
        test_placement_follows_the_trigger_while_open,
        test_all_composer_pickers_share_the_fixed_component,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
