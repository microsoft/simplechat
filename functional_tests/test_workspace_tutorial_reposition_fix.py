#!/usr/bin/env python3
"""
Functional test for workspace tutorial reposition fix.
Version: 0.239.185
Implemented in: 0.239.185

This test ensures that the personal workspace tutorial recomputes its card and
highlight position when collapses open or close and when the workspace layout shifts.
"""

import sys
from pathlib import Path


def test_workspace_tutorial_reposition_guards():
    """Verify the workspace tutorial listens for collapse and layout changes."""
    repo_root = Path(__file__).resolve().parents[1]
    tutorial_path = repo_root / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-tutorial.js"
    content = tutorial_path.read_text(encoding="utf-8")

    required_markers = [
        "function schedulePositionElements()",
        "window.requestAnimationFrame",
        "shown.bs.collapse",
        "hidden.bs.collapse",
        "shown.bs.tab",
        "ResizeObserver",
        "MutationObserver",
        "attributeFilter: [\"class\", \"style\", \"aria-expanded\"]",
        "schedulePositionElements();"
    ]

    missing = [marker for marker in required_markers if marker not in content]
    if missing:
        print("Missing workspace tutorial reposition guards:")
        for marker in missing:
            print(f"  - {marker}")
        return False

    print("Workspace tutorial reposition fix markers are present.")
    return True


if __name__ == "__main__":
    success = test_workspace_tutorial_reposition_guards()
    sys.exit(0 if success else 1)