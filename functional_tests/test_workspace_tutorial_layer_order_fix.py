#!/usr/bin/env python3
"""
Functional test for workspace tutorial layer order fix.
Version: 0.239.192
Implemented in: 0.239.192

This test ensures tutorial-owned popup surfaces are mounted inside the tutorial
layer so the walkthrough card can render above menus and example modals.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIAL_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-tutorial.js"


def test_workspace_tutorial_layer_order_fix() -> bool:
    """Verify tutorial popup surfaces are inserted before the card inside the layer."""
    print("Testing workspace tutorial layer order fix...")

    content = TUTORIAL_FILE.read_text(encoding="utf-8")
    required_markers = [
        'if (layerEl && cardEl && layerEl.contains(cardEl)) {',
        'layerEl.insertBefore(surface, cardEl);',
        'else if (layerEl) {',
        'document.body.appendChild(surface);'
    ]

    missing = [marker for marker in required_markers if marker not in content]
    if missing:
        print("Missing workspace tutorial layer-order markers:")
        for marker in missing:
            print(f"  - {marker}")
        return False

    print("Workspace tutorial layer order test passed!")
    return True


if __name__ == "__main__":
    success = test_workspace_tutorial_layer_order_fix()
    sys.exit(0 if success else 1)