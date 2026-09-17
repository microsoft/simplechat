#!/usr/bin/env python3
"""
Functional test for the release notes check fork permission fix.
Version: 0.261.009
Implemented in: 0.261.009

This test ensures that the advisory reminder steps in
.github/workflows/release-notes-check.yml cannot fail the check-release-notes job.

Pull requests opened from a fork, and pull requests opened by Dependabot, run with a
read-only GITHUB_TOKEN. The two "Post PR comment" steps call actions/github-script to
create an issue comment, which raises "Resource not accessible by integration" under a
read-only token. Before this fix that 403 failed the whole job, so every fork and
Dependabot pull request showed check-release-notes as FAILURE even when release notes
were present and correct.

The reminder is explicitly advisory - the "Validate release notes update" step always
exits 0 - so the comment steps must be marked continue-on-error.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(
    REPO_ROOT, ".github", "workflows", "release-notes-check.yml"
)

COMMENT_STEP_NAMES = [
    "Post PR comment (when notes needed but missing)",
    "Post PR comment (when latest features likely needed but missing)",
]


def _load_steps():
    """Load the check-release-notes job steps from the workflow file."""
    import yaml

    with open(WORKFLOW_PATH, "r", encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)

    return workflow["jobs"]["check-release-notes"]["steps"]


def test_comment_steps_are_non_blocking():
    """Advisory comment steps must not be able to fail the job."""
    print("Testing release notes check advisory comment steps...")

    try:
        steps = _load_steps()
        steps_by_name = {step.get("name"): step for step in steps}

        for step_name in COMMENT_STEP_NAMES:
            assert step_name in steps_by_name, (
                f"Expected step '{step_name}' in release-notes-check.yml. "
                "If the step was renamed, update this test."
            )

            step = steps_by_name[step_name]
            assert step.get("continue-on-error") is True, (
                f"Step '{step_name}' must set continue-on-error: true. Fork and "
                "Dependabot pull requests run with a read-only GITHUB_TOKEN, so "
                "creating a comment raises 'Resource not accessible by integration' "
                "and would otherwise fail the advisory check."
            )

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_validation_step_remains_blocking():
    """The real validation step must stay blocking so the check keeps its value."""
    print("Testing release notes validation step is still blocking...")

    try:
        steps = _load_steps()
        steps_by_name = {step.get("name"): step for step in steps}

        step_name = "Validate release notes update"
        assert step_name in steps_by_name, (
            f"Expected step '{step_name}' in release-notes-check.yml."
        )

        step = steps_by_name[step_name]
        assert step.get("continue-on-error") is not True, (
            f"Step '{step_name}' must remain blocking. Only the advisory comment "
            "steps should be marked continue-on-error."
        )

        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_comment_steps_are_non_blocking,
        test_validation_step_remains_blocking,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
