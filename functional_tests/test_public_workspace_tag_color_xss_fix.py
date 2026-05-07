# test_public_workspace_tag_color_xss_fix.py
"""
Functional test for public workspace tag color stored XSS hardening.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures tag colors are validated on write, repaired on read,
and rendered through DOM-safe public workspace UI paths.
"""

import os
import re
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCTIONS_DOCUMENTS_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "functions_documents.py",
)
ROUTE_FILES = {
    "personal": os.path.join(
        ROOT_DIR,
        "application",
        "single_app",
        "route_backend_documents.py",
    ),
    "group": os.path.join(
        ROOT_DIR,
        "application",
        "single_app",
        "route_backend_group_documents.py",
    ),
    "public": os.path.join(
        ROOT_DIR,
        "application",
        "single_app",
        "route_backend_public_documents.py",
    ),
}
PUBLIC_WORKSPACE_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "public",
    "public_workspace.js",
)
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
FIX_DOC = os.path.join(
    ROOT_DIR,
    "docs",
    "explanation",
    "fixes",
    "v0.241.022",
    "PUBLIC_WORKSPACE_TAG_COLOR_XSS_FIX.md",
)
UI_TEST = os.path.join(
    ROOT_DIR,
    "ui_tests",
    "test_public_workspace_tag_color_rendering.py",
)


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith("VERSION = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("VERSION assignment not found in config.py")


def assert_required_snippets(file_path, required_snippets):
    source = read_file_text(file_path)
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing required snippets in {file_path}: {missing}"
    return source


def test_shared_tag_color_helpers_harden_storage_and_read_paths():
    """Verify the shared tag helper layer validates and repairs stored colors."""
    print("🔍 Testing shared tag color helper hardening...")

    source = assert_required_snippets(
        FUNCTIONS_DOCUMENTS_FILE,
        [
            "TAG_COLOR_PATTERN = re.compile(r'^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')",
            "def normalize_tag_color(color):",
            "def get_safe_tag_color(color, tag_name):",
            "def validate_tag_color(color, tag_name):",
            "safe_color = get_safe_tag_color(color, tag_name)",
            "stored_tag_def['color'] = get_safe_tag_color(stored_tag_def.get('color'), tag_name)",
        ],
    )

    assert source.count("'color': get_safe_tag_color(tag_def.get('color'), tag_name)") >= 2, (
        "Expected get_workspace_tags() to repair stored colors for used and unused tag definitions."
    )

    print("✅ Shared tag color helper hardening passed")


def test_tag_routes_validate_and_return_normalized_colors():
    """Verify personal, group, and public tag routes all validate and persist safe colors."""
    print("🔍 Testing tag route color validation coverage...")

    route_expectations = {
        ROUTE_FILES["personal"]: [
            "validate_tag_color(color, normalized_tag)",
            "validate_tag_color(new_color, normalized_old_tag)",
            "'color': normalized_color,",
            "'message': f'Tag color updated for \"{normalized_old_tag}\"'",
        ],
        ROUTE_FILES["group"]: [
            "validate_tag_color(color, normalized_tag)",
            "validate_tag_color(new_color, normalized_old_tag)",
            "'color': normalized_color,",
            "'message': f'Tag color updated for \"{normalized_old_tag}\"'",
        ],
        ROUTE_FILES["public"]: [
            "validate_tag_color(color, normalized_tag)",
            "validate_tag_color(new_color, normalized_old_tag)",
            "'color': normalized_color,",
            "'message': f'Tag color updated for \"{normalized_old_tag}\"'",
        ],
    }

    for file_path, required_snippets in route_expectations.items():
        assert_required_snippets(file_path, required_snippets)

    print("✅ Tag route color validation coverage passed")


def test_public_workspace_tag_renderers_use_dom_safe_color_application():
    """Verify public workspace tag renderers use DOM APIs instead of HTML/event interpolation."""
    print("🔍 Testing public workspace tag renderer hardening...")

    source = assert_required_snippets(
        PUBLIC_WORKSPACE_JS,
        [
            "const publicHexColorPattern = /^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;",
            "function normalizePublicHexColor(color, fallback = '#6c757d') {",
            "function createPublicTagBadgeElement(tagName, color, className = 'tag-badge') {",
            "cards.appendChild(createPublicFolderCard(item, canManageTags));",
            "renderPublicTagBadges(doc.tags || [], detailsRow.querySelector('.public-doc-tag-badges'));",
            "applyPublicBackgroundColor(colorSwatch, tag.color);",
            "const badge = createPublicTagBadgeElement(tag.name, tag.color, 'badge me-2');",
            "const badge = createPublicTagBadgeElement(tagName, getPublicTagColorByName(tagName), 'badge me-1');",
        ],
    )

    forbidden_snippets = [
        'onclick="changePublicTagColor(',
        'onclick="renamePublicTag(',
        'onclick="deletePublicTag(',
        'onclick="window.editPublicTagInModal(',
        'onclick="window.deletePublicTagFromModal(',
        'onclick="window.removePublicDocSelectedTag(',
        'style="background-color:${tag.color};color:${textColor};"',
        'style="background-color:${color};color:${textColor};"',
        'function renderPublicTagBadges(tags, maxDisplay = 3) {',
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in source]
    assert not present, f"Unexpected unsafe tag renderer snippets found: {present}"

    forbidden_patterns = [
        r'onclick="[^\"]*(changePublicTagColor|editPublicTagInModal|deletePublicTagFromModal|removePublicDocSelectedTag|renamePublicTag|deletePublicTag)',
        r'style="[^\"]*\$\{(tag\.color|color|textColor)',
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, source), f"Unsafe tag rendering pattern still present: {pattern}"

    print("✅ Public workspace tag renderer hardening passed")


def test_fix_artifacts_and_version_are_in_sync():
    """Verify versioned regression artifacts landed for this fix."""
    print("🔍 Testing fix artifacts and version alignment...")

    assert read_config_version() == "0.241.022"
    assert os.path.exists(FIX_DOC), f"Expected fix documentation at {FIX_DOC}"
    assert os.path.exists(UI_TEST), f"Expected UI regression test at {UI_TEST}"

    fix_doc_source = read_file_text(FIX_DOC)
    assert "Fixed/Implemented in version: **0.241.022**" in fix_doc_source
    assert "functional_tests/test_public_workspace_tag_color_xss_fix.py" in fix_doc_source
    assert "ui_tests/test_public_workspace_tag_color_rendering.py" in fix_doc_source

    print("✅ Fix artifacts and version alignment passed")


if __name__ == "__main__":
    tests = [
        test_shared_tag_color_helpers_harden_storage_and_read_paths,
        test_tag_routes_validate_and_return_normalized_colors,
        test_public_workspace_tag_renderers_use_dom_safe_color_application,
        test_fix_artifacts_and_version_are_in_sync,
    ]

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        test()

    print(f"\n📊 Results: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)