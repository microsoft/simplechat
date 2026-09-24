# test_chat_clipboard_paste_upload_support.py
#!/usr/bin/env python3
"""
Functional test for chat clipboard paste upload support.
Version: 0.261.046
Implemented in: 0.241.056; expanded in: 0.261.032; hardened in: 0.261.046

This test ensures chat paste uploads route clipboard files through the shared
chat upload helper, normalize missing clipboard filenames, preserve normal text
paste behavior after image uploads, support dropped files in the chat input,
and provide actionable errors when the browser cannot read an upload.
"""

import os
import re
import sys
from test_support.versioning import assert_app_version_at_least


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT_INPUT_ACTIONS_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "chat",
    "chat-input-actions.js",
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "config.py",
)


def read_file(path):
    """Read a UTF-8 text file from the repo."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_chat_clipboard_paste_reuses_shared_upload_helper():
    """Verify selected, pasted, and dropped file flows use the same upload helper."""
    print("🔍 Testing chat clipboard upload helper reuse...")

    content = read_file(CHAT_INPUT_ACTIONS_FILE)

    required_snippets = [
        'function beginChatFileUpload(filesLike, options = {}) {',
        'window.UserAgreementManager.checkBeforeUpload(',
        'uploadFilesInSequence(uploadFiles);',
        'beginChatFileUpload([file], { fallbackPrefix: "chat_upload" });',
        'beginChatFileUpload(clipboardFiles, { fallbackPrefix: "pasted_file" });',
        'beginChatFileUpload(droppedFiles, { fallbackPrefix: "dropped_file" });',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f"Missing shared upload helper snippets: {missing}"

    helper_reuse_count = content.count('beginChatFileUpload([file], { fallbackPrefix: "chat_upload" });')
    assert helper_reuse_count == 2, "Expected both selected-file paths to reuse beginChatFileUpload."

    print("✅ Shared upload helper reuse passed")


def test_chat_clipboard_paste_handler_normalizes_missing_filenames():
    """Verify clipboard uploads normalize nameless files before posting them."""
    print("🔍 Testing clipboard filename normalization and paste binding...")

    content = read_file(CHAT_INPUT_ACTIONS_FILE)

    required_snippets = [
        'const userInputEl = document.getElementById("user-input");',
        'function inferExtensionFromMimeType(mimeType) {',
        'function normalizeUploadFile(file, fallbackPrefix = "clipboard_upload") {',
        'const normalizedName = `${fallbackPrefix}_${Date.now()}.${extension}`;',
        'return new File([file], normalizedName, {',
        'function getClipboardFiles(clipboardData) {',
        'function clipboardHasPlainText(clipboardData) {',
        'function hasNamedFile(files) {',
        'if (clipboardHasPlainText(clipboardData) && !hasNamedFile(clipboardFiles)) {',
        'userInputEl.addEventListener("paste", (event) => {',
        'const clipboardFiles = getClipboardFiles(event.clipboardData);',
        'event.preventDefault();',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f"Missing clipboard paste upload snippets: {missing}"

    assert '"image/png": "png"' in content, "Expected clipboard MIME fallback map to include image/png."

    print("✅ Clipboard filename normalization and paste binding passed")


def test_chat_drag_and_drop_upload_binding():
    """Verify chat input drag-and-drop uploads files and preserves text drops."""
    print("🔍 Testing chat drag-and-drop upload binding...")

    content = read_file(CHAT_INPUT_ACTIONS_FILE)

    required_snippets = [
        'const chatDropZoneEl = document.querySelector(".chat-input-container");',
        'function hasFileTransfer(dataTransfer) {',
        'function getDataTransferFiles(dataTransfer) {',
        'function setChatDropActive(isActive) {',
        'chatDropZoneEl.addEventListener("drop", (event) => {',
        'const droppedFiles = getDataTransferFiles(event.dataTransfer);',
        'beginChatFileUpload(droppedFiles, { fallbackPrefix: "dropped_file" });',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f"Missing drag-and-drop upload snippets: {missing}"

    print("✅ Chat drag-and-drop upload binding passed")


def test_chat_upload_reports_unreadable_files_with_recovery_guidance():
    """Verify local file access failures identify the document and recovery steps."""
    print("🔍 Testing unreadable chat upload guidance...")

    content = read_file(CHAT_INPUT_ACTIONS_FILE)

    required_snippets = [
        "async function ensureUploadFileIsReadable(file) {",
        "await file.slice(0, Math.min(file.size, 1)).arrayBuffer();",
        "await ensureUploadFileIsReadable(file);",
        'The browser could not read "${fileName}".',
        "Close the file in other apps then try again.",
        'The browser could not upload "${fileName}".',
        "The file may be open in another app, unavailable from cloud storage, or the network connection may have been interrupted.",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f"Missing unreadable upload guidance snippets: {missing}"
    assert re.search(
        r"catch \(error\) \{\s*const fileName = String\(file\?\.name \|\| \"selected file\"\)\.trim\(\) \|\| \"selected file\";",
        content,
    ), "Expected fetch upload failures to include the selected file name in recovery guidance."
    assert "error instanceof TypeError" not in content, (
        "Rejected upload requests must not depend on a browser-realm-specific error type."
    )

    print("✅ Unreadable chat upload guidance passed")


def test_config_version_is_bumped_for_chat_clipboard_upload_support():
    """Verify config version was bumped for the clipboard paste upload feature."""
    print("🔍 Testing config version bump...")

    assert_app_version_at_least("0.261.032")

    print("✅ Config version bump passed")


if __name__ == "__main__":
    tests = [
        test_chat_clipboard_paste_reuses_shared_upload_helper,
        test_chat_clipboard_paste_handler_normalizes_missing_filenames,
        test_chat_drag_and_drop_upload_binding,
        test_chat_upload_reports_unreadable_files_with_recovery_guidance,
        test_config_version_is_bumped_for_chat_clipboard_upload_support,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)