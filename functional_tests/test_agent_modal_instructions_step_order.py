#!/usr/bin/env python3
"""
Functional test for the agent modal Instructions step reorder.
Version: 0.250.214
Implemented in: 0.250.214

This test ensures that the agent configuration modal presents Instructions
after Actions and Assigned Knowledge, and that the stepper drives navigation
from the named step map instead of hard-coded step numbers.

Refs: https://github.com/microsoft/simplechat/issues/1257
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
MODAL_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"
STEPPER_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "agent_modal_stepper.js"

EXPECTED_STEP_LABELS = [
    "Basic Info",
    "Model & Connection",
    "Actions",
    "Knowledge",
    "Instructions",
    "Advanced",
    "Summary",
]

EXPECTED_STEP_KEYS = [
    "basic",
    "model",
    "actions",
    "knowledge",
    "instructions",
    "advanced",
    "summary",
]

# Step number -> a marker that must live inside that step pane.
EXPECTED_STEP_MARKERS = {
    1: 'id="agent-display-name"',
    2: 'id="agent-foundry-fields"',
    3: 'id="agent-actions-container"',
    4: 'id="agent-assigned-knowledge-enabled"',
    5: 'id="agent-instructions-container"',
    6: 'id="agent-additional-settings"',
    7: 'id="summary-display-name"',
}


def read_text(path):
    return path.read_text(encoding="utf-8")


def split_step_panes(template_source):
    """Return {step_number: pane_html} by slicing between agent-step anchors."""
    anchors = [
        (int(match.group(1)), match.start())
        for match in re.finditer(r'id="agent-step-(\d)"', template_source)
    ]
    panes = {}
    for index, (step_number, start) in enumerate(anchors):
        end = anchors[index + 1][1] if index + 1 < len(anchors) else len(template_source)
        panes[step_number] = template_source[start:end]
    return panes


def test_step_indicator_order():
    """The visible step indicators must be in the new order."""
    print("Testing agent modal step indicator order...")
    try:
        template_source = read_text(MODAL_TEMPLATE)
        labels = re.findall(r'<div class="step-label">([^<]+)</div>', template_source)

        assert labels == EXPECTED_STEP_LABELS, (
            f"Unexpected step indicator order.\n  found={labels}\n  want={EXPECTED_STEP_LABELS}"
        )

        step_numbers = [int(value) for value in re.findall(r'class="step-indicator" data-step="(\d)"', template_source)]
        assert step_numbers == [1, 2, 3, 4, 5, 6, 7], f"Unexpected data-step order: {step_numbers}"

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_step_panes_match_new_order():
    """Each numbered step pane must contain the content for its new position."""
    print("Testing agent modal step pane assignment...")
    try:
        template_source = read_text(MODAL_TEMPLATE)
        panes = split_step_panes(template_source)

        assert sorted(panes) == [1, 2, 3, 4, 5, 6, 7], f"Unexpected step panes: {sorted(panes)}"

        for step_number, marker in EXPECTED_STEP_MARKERS.items():
            assert marker in panes[step_number], (
                f"Expected {marker} inside #agent-step-{step_number}."
            )

        instructions_start = template_source.index('id="agent-step-5"')
        knowledge_start = template_source.index('id="agent-step-4"')
        actions_start = template_source.index('id="agent-step-3"')
        assert actions_start < knowledge_start < instructions_start, (
            "Step panes should be laid out in Actions, Knowledge, Instructions order."
        )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_stepper_uses_named_step_map():
    """Navigation and validation must branch on step keys, not magic numbers."""
    print("Testing agent modal stepper step-key map...")
    try:
        stepper_source = read_text(STEPPER_JS)

        step_keys_match = re.search(
            r"const AGENT_STEP_KEYS = Object\.freeze\(\[(.*?)\]\)",
            stepper_source,
            re.DOTALL,
        )
        assert step_keys_match, "Expected an AGENT_STEP_KEYS array in agent_modal_stepper.js."

        found_keys = re.findall(r"'([a-z]+)'", step_keys_match.group(1))
        assert found_keys == EXPECTED_STEP_KEYS, (
            f"Unexpected AGENT_STEP_KEYS.\n  found={found_keys}\n  want={EXPECTED_STEP_KEYS}"
        )

        assert "this.maxSteps = AGENT_STEP_KEYS.length;" in stepper_source, (
            "maxSteps should derive from AGENT_STEP_KEYS so the map stays authoritative."
        )

        for helper in ("getStepKey(", "getStepNumber(", "getStepElement(", "isOnStep("):
            assert helper in stepper_source, f"Expected step helper {helper} in agent_modal_stepper.js."

        assert "switch (this.getStepKey())" in stepper_source, (
            "validateCurrentStep should switch on the step key."
        )
        assert "switch (this.getStepKey(stepNumber))" in stepper_source, (
            "showStep should switch on the step key."
        )

        for step_key in EXPECTED_STEP_KEYS:
            assert f"case '{step_key}':" in stepper_source, (
                f"Expected a case for the '{step_key}' step key."
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_no_hardcoded_step_numbers_remain():
    """The old numeric step branches must be gone so the reorder cannot silently break."""
    print("Testing that hard-coded agent step numbers were removed...")
    try:
        stepper_source = read_text(STEPPER_JS)

        forbidden_patterns = [
            (r"getElementById\('agent-step-\d'\)", "direct #agent-step-N lookup"),
            (r"this\.currentStep === [2-6]\b", "numeric currentStep comparison for a reorderable step"),
            (r"if \(stepNumber === \d\)", "numeric stepNumber branch"),
            (r"case [1-7]: //", "numeric validateCurrentStep case"),
        ]

        for pattern, description in forbidden_patterns:
            matches = re.findall(pattern, stepper_source)
            assert not matches, (
                f"Found {description} in agent_modal_stepper.js: {matches}. "
                "Use the AGENT_STEP_KEYS helpers instead."
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_instructions_step_has_context_panel():
    """The Instructions step must expose the selected actions and knowledge."""
    print("Testing Instructions step reference panel...")
    try:
        template_source = read_text(MODAL_TEMPLATE)
        stepper_source = read_text(STEPPER_JS)
        panes = split_step_panes(template_source)
        instructions_pane = panes[5]

        for element_id in (
            "agent-instructions-context-panel",
            "agent-instructions-context-body",
            "agent-instructions-context-actions",
            "agent-instructions-context-knowledge",
            "agent-instructions-context-actions-count",
            "agent-instructions-context-knowledge-count",
        ):
            assert f'id="{element_id}"' in instructions_pane, (
                f"Expected #{element_id} inside the Instructions step."
            )

        assert 'data-bs-toggle="collapse"' in instructions_pane, (
            "The reference panel should be collapsible."
        )

        assert "getSelectedActionsWithCapabilities()" in stepper_source, (
            "Expected a selected-actions-with-capabilities accessor."
        )
        assert "getAssignedKnowledgeReference()" in stepper_source, (
            "Expected an assigned knowledge reference accessor."
        )
        assert "renderInstructionsContextPanel()" in stepper_source, (
            "Expected the reference panel renderer."
        )
        assert "prepareInstructionsContext()" in stepper_source, (
            "Expected the Instructions step to prepare its context on entry."
        )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_draft_instructions_sends_context():
    """Draft Instructions must post the selected actions and assigned knowledge."""
    print("Testing draft instructions request payload...")
    try:
        stepper_source = read_text(STEPPER_JS)
        draft_index = stepper_source.index("/api/agents/draft-instructions")
        draft_block = stepper_source[draft_index:draft_index + 900]

        assert "selected_actions: this.getSelectedActionsWithCapabilities()" in draft_block, (
            "Draft request should include selected_actions."
        )
        assert "assigned_knowledge: this.getAssignedKnowledgeReference()" in draft_block, (
            "Draft request should include assigned_knowledge."
        )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least(
        "0.250.214",
        reason="Agent modal Instructions step reorder landed in 0.250.214.",
    )

    tests = [
        test_step_indicator_order,
        test_step_panes_match_new_order,
        test_stepper_uses_named_step_map,
        test_no_hardcoded_step_numbers_remain,
        test_instructions_step_has_context_panel,
        test_draft_instructions_sends_context,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
