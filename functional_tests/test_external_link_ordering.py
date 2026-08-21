# test_external_link_ordering.py
#!/usr/bin/env python3
"""
Functional test for admin external-link ordering.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures the external-link table exposes both ordering actions and
wires them to the array reordering and persistence flow.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_SETTINGS_JS = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "static",
    "js",
    "admin",
    "admin_settings.js",
)


def read_admin_settings_javascript():
    """Read the admin settings JavaScript for focused regression checks."""
    with open(ADMIN_SETTINGS_JS, "r", encoding="utf-8") as javascript_file:
        return javascript_file.read()


def test_external_link_ordering_controls_are_wired():
    """Verify both ordering controls dispatch to the shared move handler."""
    javascript = read_admin_settings_javascript()

    assert "external-link-move-up-btn" in javascript
    assert "external-link-move-down-btn" in javascript
    assert "handleMoveExternalLink(indexAttr, -1)" in javascript
    assert "handleMoveExternalLink(indexAttr, 1)" in javascript


def test_external_link_move_updates_saved_order():
    """Verify moving links rerenders and updates the existing JSON field."""
    javascript = read_admin_settings_javascript()
    move_handler_start = javascript.index("function handleMoveExternalLink")
    next_function_start = javascript.index(
        "/**",
        move_handler_start,
    )
    move_handler = javascript[move_handler_start:next_function_start]

    assert "[externalLinks[index], externalLinks[destinationIndex]]" in move_handler
    assert "renderExternalLinks();" in move_handler
    assert "markFormAsModified();" in move_handler

    render_start = javascript.index("function renderExternalLinks")
    render_end = javascript.index("/**", render_start)
    render_function = javascript[render_start:render_end]
    assert "updateExternalLinksJsonInput();" in render_function


def main():
    """Run all external-link ordering regression checks."""
    tests = [
        test_external_link_ordering_controls_are_wired,
        test_external_link_move_updates_saved_order,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
