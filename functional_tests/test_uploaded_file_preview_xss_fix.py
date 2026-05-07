# test_uploaded_file_preview_xss_fix.py
"""
Functional test for uploaded file preview XSS hardening.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures uploaded file preview rendering no longer injects raw file
content into modal HTML and that current tabular previews build their DOM with
text nodes instead of untrusted HTML interpolation.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    "v0.241.022",
    "UPLOADED_FILE_PREVIEW_XSS_FIX.md",
)


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def test_uploaded_file_preview_uses_safe_rendering_boundaries():
    """Verify the preview modal no longer feeds file content into dynamic HTML sinks."""
    print("🔍 Testing uploaded file preview rendering boundaries...")

    source = read_file_text(CHAT_INPUT_ACTIONS_JS)

    required_snippets = [
        'downloadBtnContainer.replaceChildren();',
        'const downloadLink = document.createElement("a");',
        'const isLegacyHtmlTableContent = /^<table[\\s\\S]*<\\/table>$/i.test(trimmedContent);',
        'renderPreformattedText(fileContentElement, fileContent);',
        'const tableWrapper = buildCsvTableElement(fileContent);',
        'headerCell.textContent = header;',
        'cellElement.textContent = cell;',
        'pre.textContent = String(text ?? "");',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing uploaded file preview hardening snippets: {missing}"

    forbidden_snippets = [
        'fileContentElement.innerHTML = `<div class="table-responsive">${tableHTML}</div>`;',
        'fileContentElement.innerHTML = `<div class="table-responsive">${fileContent}</div>`;',
        'fileContentElement.innerHTML = `<pre style="white-space: pre-wrap;">${fileContent}</pre>`;',
        '!fileContent.trim().startsWith(\'<\')',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unsafe uploaded file preview snippets found: {present}"

    print("✅ Uploaded file preview rendering boundaries passed")


def test_fix_documentation_and_version_are_in_sync():
    """Verify the fix note and current config version landed together."""
    print("🔍 Testing uploaded file preview fix documentation and version...")

    assert read_config_version() == "0.241.022"

    assert os.path.exists(FIX_DOC), f"Expected fix documentation at {FIX_DOC}"
    fix_doc = read_file_text(FIX_DOC)
    assert "Fixed/Implemented in version: **0.241.022**" in fix_doc
    assert "legacy html table payloads now render as inert preformatted text" in fix_doc.lower()
    assert "functional_tests/test_uploaded_file_preview_xss_fix.py" in fix_doc
    assert "ui_tests/test_uploaded_file_preview_escaping.py" in fix_doc

    print("✅ Uploaded file preview fix documentation and version passed")


if __name__ == "__main__":
    tests = [
        test_uploaded_file_preview_uses_safe_rendering_boundaries,
        test_fix_documentation_and_version_are_in_sync,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)