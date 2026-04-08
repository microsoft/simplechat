# test_group_document_delete_modal_wiring.py
"""
Functional test for group document delete modal wiring.
Version: 0.241.004
Implemented in: 0.241.004

This test ensures the group workspace delete-choice modal is rendered as
standalone page markup and is not injected through the dynamic status alert.
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
GROUP_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "group_workspaces.html"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_group_document_delete_modal_wiring() -> bool:
    print("Testing group document delete modal wiring...")

    config_content = read_text(CONFIG_FILE)
    template_content = read_text(GROUP_TEMPLATE_FILE)
    scripts_start = template_content.index("{% block scripts %}")
    content_markup = template_content[:scripts_start]

    assert 'VERSION = "0.241.004"' in config_content, "Config version marker is not current."

    for marker in [
        'id="groupDocumentDeleteModal"',
        'id="groupDocumentDeleteModalLabel"',
        'id="groupDocumentDeleteModalBody"',
        'id="groupDeleteCurrentBtn"',
        'id="groupDeleteAllBtn"',
    ]:
        assert marker in content_markup, f"Missing standalone modal marker before scripts block: {marker}"

    alert_assignment = re.search(r"alertBox\.innerHTML\s*=\s*`([\s\S]*?)`;", template_content)
    assert alert_assignment is not None, "Could not locate the group status alert template assignment."
    assert "groupDocumentDeleteModal" not in alert_assignment.group(1), (
        "Group delete modal should not be injected through alertBox.innerHTML."
    )

    required_script_markers = [
        'const groupDocumentDeleteModalElement = document.getElementById(',
        'function isGroupDocumentDeleteModalReady()',
        'function promptGroupDeleteMode(documentCount = 1)',
        'groupDocumentDeleteModal.show();',
    ]
    missing_script_markers = [marker for marker in required_script_markers if marker not in template_content]
    assert not missing_script_markers, f"Missing group delete modal script markers: {missing_script_markers}"

    print("Group document delete modal wiring test passed!")
    return True


if __name__ == "__main__":
    success = test_group_document_delete_modal_wiring()
    sys.exit(0 if success else 1)