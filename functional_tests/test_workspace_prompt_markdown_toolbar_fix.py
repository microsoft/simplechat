#!/usr/bin/env python3
"""
Functional test for app-wide markdown editor fixes.
Version: 0.239.198
Implemented in: 0.239.198

This test ensures shared markdown editor fixes remain available across the app,
including toolbar fallbacks, public prompt editor loading, and agent
instructions markdown editing.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "base.html"
PUBLIC_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "public_workspaces.html"
AGENT_STEPPER = REPO_ROOT / "application" / "single_app" / "static" / "js" / "agent_modal_stepper.js"


def test_workspace_prompt_markdown_toolbar_fix() -> bool:
    """Verify markdown editor fixes are wired through shared app paths."""
    print("Testing app-wide markdown editor fixes...")

    base_content = BASE_TEMPLATE.read_text(encoding="utf-8")
    public_content = PUBLIC_TEMPLATE.read_text(encoding="utf-8")
    agent_stepper_content = AGENT_STEPPER.read_text(encoding="utf-8")

    checks = {
        '.editor-toolbar a.fa-code:before { content: "</>"; font-size: 11px; }': base_content,
        '.editor-toolbar a.fa-header:before { content: "#"; }': base_content,
        '.editor-toolbar a.fa-minus:before { content: "\\2014"; }': base_content,
        '.editor-toolbar a.fa-eraser:before { content: "\\232B"; }': base_content,
        '<script src="/static/js/simplemde/simplemde.min.js"></script>': public_content,
        'this.instructionsEditor = null;': agent_stepper_content,
        'this.instructionsEditor = new window.SimpleMDE({': agent_stepper_content,
        'this.getInstructionsValue()': agent_stepper_content,
        "this.setInstructionsValue(agent.instructions || '');": agent_stepper_content,
        "this.refreshInstructionsEditor(this.currentStep === 3 && this.currentAgentType !== 'aifoundry');": agent_stepper_content,
    }

    missing = [marker for marker, content in checks.items() if marker not in content]
    if missing:
        print("Missing markdown editor fix markers:")
        for marker in missing:
            print(f"  - {marker}")
        return False

    print("App-wide markdown editor fixes test passed!")
    return True


if __name__ == "__main__":
    success = test_workspace_prompt_markdown_toolbar_fix()
    sys.exit(0 if success else 1)