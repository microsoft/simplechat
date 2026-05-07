# test_stored_xss_chat_modal_filename_fix.py
"""
Functional test for chat modal filename XSS hardening.
Version: 0.241.018
Implemented in: 0.241.018

This test ensures chat citation and uploaded-file modal titles render
attacker-controlled filenames as inert text on first display.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_CITATIONS_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "chat",
    "chat-citations.js",
)
CHAT_INPUT_ACTIONS_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "chat",
    "chat-input-actions.js",
)
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "v0.241.018",
    "CITATION_AND_FILE_MODAL_FILENAME_XSS_FIX.md",
)


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def test_citation_modal_title_uses_text_content_for_filename():
    """Verify the citation modal never injects fileName into first-render HTML."""
    print("🔍 Testing citation modal title escaping...")

    source = read_file_text(CHAT_CITATIONS_JS)

    required_snippets = [
        '            <h5 class="modal-title"></h5>',
        '    modalTitle.textContent = `Source: ${fileName}, Page: ${pageNumber}`;',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing citation modal hardening snippets: {missing}"

    forbidden_snippets = [
        '            <h5 class="modal-title">Source: ${fileName}, Page: ${pageNumber}</h5>',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected inline filename interpolation found: {present}"

    print("✅ Citation modal title escaping passed")


def test_uploaded_file_modal_title_uses_text_content_for_filename():
    """Verify the uploaded-file modal never injects filename into first-render HTML."""
    print("🔍 Testing uploaded-file modal title escaping...")

    source = read_file_text(CHAT_INPUT_ACTIONS_JS)

    required_snippets = [
        '            <h5 class="modal-title"></h5>',
        '    modalTitle.textContent = `Uploaded File: ${filename}`;',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing uploaded-file modal hardening snippets: {missing}"

    forbidden_snippets = [
        '            <h5 class="modal-title">Uploaded File: ${filename}</h5>',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected inline filename interpolation found: {present}"

    print("✅ Uploaded-file modal title escaping passed")


def test_fix_documentation_and_version_exist():
    """Verify the version bump and fix documentation landed for this change."""
    print("🔍 Testing chat modal filename fix documentation and version...")

    assert read_config_version() == "0.241.018"
    assert os.path.exists(FIX_DOC), f"Expected fix documentation at {FIX_DOC}"

    print("✅ Chat modal filename fix documentation and version passed")


if __name__ == "__main__":
    tests = [
        test_citation_modal_title_uses_text_content_for_filename,
        test_uploaded_file_modal_title_uses_text_content_for_filename,
        test_fix_documentation_and_version_exist,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)