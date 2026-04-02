# test_group_workspace_initial_documents_fetch_fix.py
"""
Functional test for group workspace initial document fetch fix.
Version: 0.240.027
Implemented in: 0.240.027

This test ensures that the group workspace document loader rebuilds its query
parameters before the first fetch and does not trigger bulk-delete confirmation
logic while the page is still initializing.
"""

import os
import re
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUP_WORKSPACE_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "group_workspaces.html",
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "config.py",
)


def read_file(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def extract_fetch_group_documents_block(content):
    match = re.search(
        r"function fetchGroupDocuments\(\) \{(?P<body>.*?)\n  \}\n\n  // --- Render Group Document Row ---",
        content,
        re.DOTALL,
    )
    assert match, "Could not locate fetchGroupDocuments block in group_workspaces.html"
    return f"function fetchGroupDocuments() {{{match.group('body')}\n  }}"


def test_group_workspace_initial_fetch_builds_params_without_delete_prompt():
    """Verify the initial group document fetch path does not invoke delete UI."""
    print("🔍 Testing group workspace initial document fetch path...")

    content = read_file(GROUP_WORKSPACE_TEMPLATE)
    fetch_block = extract_fetch_group_documents_block(content)

    required_snippets = [
        "const params = new URLSearchParams({",
        "page: groupDocsCurrentPage,",
        "page_size: groupDocsPageSize,",
        "params.append(\"search\", groupDocsSearchTerm);",
        "params.append(\"classification\", groupDocsClassificationFilter);",
        "params.append(\"author\", groupDocsAuthorFilter);",
        "params.append(\"keywords\", groupDocsKeywordsFilter);",
        "params.append(\"abstract\", groupDocsAbstractFilter);",
        "params.append(\"tags\", groupDocsTagsFilter);",
        "fetch(`/api/group_documents?${params.toString()}`)",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in fetch_block]
    assert not missing, f"Missing required fetchGroupDocuments snippets: {missing}"

    forbidden_snippets = [
        "promptGroupDeleteMode(",
        "requestGroupDocumentDeletion(",
        "Promise.allSettled(deletePromises)",
    ]
    present = [snippet for snippet in forbidden_snippets if snippet in fetch_block]
    assert not present, f"Unexpected delete flow found in fetchGroupDocuments: {present}"

    print("✅ Group workspace initial fetch path passed")
    return True


def test_config_version_is_bumped_for_group_workspace_fetch_fix():
    """Verify config version was bumped for the group workspace fetch fix."""
    print("🔍 Testing config version bump...")

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.240.027"' in config_content, "Expected config.py version 0.240.027"

    print("✅ Config version bump passed")
    return True


if __name__ == "__main__":
    tests = [
        test_group_workspace_initial_fetch_builds_params_without_delete_prompt,
        test_config_version_is_bumped_for_group_workspace_fetch_fix,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)