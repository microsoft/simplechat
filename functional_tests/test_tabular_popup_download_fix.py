#!/usr/bin/env python3
# test_tabular_popup_download_fix.py
"""
Functional test for the tabular popup download fix.
Version: 0.239.124
Implemented in: 0.239.124

This test ensures that the chat tabular preview modal uses an authenticated
fetch-to-blob download flow so download failures are surfaced in-app instead of
failing silently through the browser-managed anchor path.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_tabular_popup_uses_fetch_download_flow():
    """Verify the tabular popup uses a controlled fetch download flow."""
    print("🔍 Testing tabular popup fetch download flow...")

    js_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        'application',
        'single_app',
        'static',
        'js',
        'chat',
        'chat-enhanced-citations.js'
    )

    if not os.path.exists(js_file_path):
        print(f"❌ Enhanced citations JS file not found: {js_file_path}")
        return False

    with open(js_file_path, 'r', encoding='utf-8') as handle:
        js_content = handle.read()

    required_snippets = [
        'async function downloadTabularFile(downloadUrl, fallbackFilename, downloadBtn)',
        'fetch(downloadUrl, {',
        "credentials: 'same-origin'",
        'const blob = await response.blob();',
        'triggerBlobDownload(blob, downloadFilename);',
        "showToast(error.message || 'Could not download file.', 'danger');",
        'downloadBtn.onclick = (event) => {',
    ]

    for snippet in required_snippets:
        if snippet not in js_content:
            print(f"❌ Missing required download flow snippet: {snippet}")
            return False

    print("✅ Controlled fetch download flow snippets found")
    return True


def test_tabular_popup_no_longer_uses_blank_target_anchor():
    """Verify the modal download control no longer relies on a blank-target anchor."""
    print("🔍 Testing tabular popup download control markup...")

    js_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        'application',
        'single_app',
        'static',
        'js',
        'chat',
        'chat-enhanced-citations.js'
    )

    with open(js_file_path, 'r', encoding='utf-8') as handle:
        js_content = handle.read()

    if '<button type="button" id="enhanced-tabular-download" class="btn btn-primary btn-sm">' not in js_content:
        print("❌ Download control is not rendered as a button")
        return False

    disallowed_snippets = [
        'downloadBtn.href = downloadUrl;',
        'downloadBtn.download = fileName;',
        'target="_blank" rel="noopener noreferrer"',
    ]

    for snippet in disallowed_snippets:
        if snippet in js_content:
            print(f"❌ Found old anchor-based download snippet: {snippet}")
            return False

    print("✅ Download control no longer uses the old anchor path")
    return True


def test_version_updated_for_fix():
    """Verify config.py reflects the new fix version."""
    print("🔍 Testing version update for tabular popup download fix...")

    config_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        'application',
        'single_app',
        'config.py'
    )

    with open(config_file_path, 'r', encoding='utf-8') as handle:
        config_content = handle.read()

    if 'VERSION = "0.239.124"' not in config_content:
        print("❌ Version not updated to 0.239.124")
        return False

    print("✅ Version properly updated to 0.239.124")
    return True


if __name__ == '__main__':
    tests = [
        test_tabular_popup_uses_fetch_download_flow,
        test_tabular_popup_no_longer_uses_blank_target_anchor,
        test_version_updated_for_fix,
    ]

    results = []
    for test in tests:
        print()
        results.append(test())

    success = all(results)
    print(f"\n📊 Test Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)