# test_assigned_knowledge_active_documents_ui.py
"""
Functional test for Assigned Knowledge active documents guidance.
Version: 0.241.119
Implemented in: 0.241.119

This test ensures that the agent modal explains Assigned Knowledge as
source workspaces, optional limits, and final active documents, and that
the browser preview logic matches backend all-tag filter semantics.
"""

import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "application" / "single_app" / "config.py"
TEMPLATE_PATH = ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"
STEPPER_PATH = ROOT / "application" / "single_app" / "static" / "js" / "agent_modal_stepper.js"
EXPECTED_VERSION = "0.241.119"


def _read_text(path):
    return path.read_text(encoding="utf-8")


def _get_config_version():
    for line in _read_text(CONFIG_PATH).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith("VERSION = "):
            return stripped_line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION was not found in config.py")


def test_assigned_knowledge_modal_uses_active_document_language():
    """Validate the modal exposes help, source pools, optional limits, and active documents."""
    print("Testing Assigned Knowledge active-document language...")
    template = _read_text(TEMPLATE_PATH)

    required_snippets = [
        'id="agent-assigned-knowledge-help-toggle"',
        'id="agent-assigned-knowledge-help"',
        "Source Workspaces",
        "Tag Limits",
        "Limit to Specific Documents",
        "Active Documents",
        "modal-xl agent-modal-dialog",
        'id="agent-assigned-knowledge-active-summary"',
        "final indexed documents the agent will use in chat",
    ]
    missing_snippets = [snippet for snippet in required_snippets if snippet not in template]
    if missing_snippets:
        raise AssertionError(f"Missing expected modal text or controls: {missing_snippets}")

    print("Assigned Knowledge modal language is present.")
    return True


def test_assigned_knowledge_preview_matches_backend_tag_semantics():
    """Validate the preview requires all selected tags and shows active-document counts."""
    print("Testing Assigned Knowledge preview semantics...")
    stepper = _read_text(STEPPER_PATH)

    required_snippets = [
        "selectedTags.every(tag => documentTags.has(tag))",
        "matchesSelectedTags",
        "No active documents match the current limits",
        "active document",
        "documents matching all ${tagCount} selected tag limits",
        "tag limit",
        "specific document",
    ]
    missing_snippets = [snippet for snippet in required_snippets if snippet not in stepper]
    if missing_snippets:
        raise AssertionError(f"Missing expected preview logic or wording: {missing_snippets}")

    print("Assigned Knowledge preview semantics match backend tag filtering.")
    return True


def test_version_header_matches_config():
    """Validate this regression test tracks the current application version."""
    config_version = _get_config_version()
    if config_version != EXPECTED_VERSION:
        raise AssertionError(
            f"Expected config.py version {EXPECTED_VERSION}, found {config_version}"
        )
    print(f"Version header matches config.py: {config_version}")
    return True


def main():
    tests = [
        test_assigned_knowledge_modal_uses_active_document_language,
        test_assigned_knowledge_preview_matches_backend_tag_semantics,
        test_version_header_matches_config,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as ex:
            print(f"Test failed: {ex}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())