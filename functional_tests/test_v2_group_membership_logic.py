#!/usr/bin/env python3
# test_v2_group_membership_logic.py
"""
Functional test for the V2 group membership adapter's logic.
Version: 0.261.155
Implemented in: 0.261.155

This test runs `functional_tests/test_v2_group_membership_logic.mjs`, which executes the real
`application/v2_ui/src/lib/groupMembership.ts` under Node's type stripping, with controlled HTTP.
It ensures the strict member-list, request-list and write-answer readers refuse every malformed
shape, that each client call sends exactly the documented method, path and body (no body on the
reads, the removal and the decisions), that the people search reader skips unusable entries, that
refusals keep the server's reviewed text and code, and that the CSV import follows the classic
manage page's format, rules and messages.
"""

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "functional_tests" / "test_v2_group_membership_logic.mjs"


def test_group_membership_adapter_logic():
    """Run the real adapter's logic checks under Node."""
    print("Testing the V2 group membership adapter logic...")
    node = shutil.which("node")
    assert node, "Node.js is required to execute the V2 group membership adapter."
    result = subprocess.run([node, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "group membership logic checks passed." in result.stdout, result.stdout
    print("Group membership adapter logic passed!")


if __name__ == "__main__":
    try:
        test_group_membership_adapter_logic()
    except AssertionError as error:
        print(f"Test failed: {error}")
        sys.exit(1)
    sys.exit(0)
