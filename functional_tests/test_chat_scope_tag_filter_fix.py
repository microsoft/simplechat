# test_chat_scope_tag_filter_fix.py
"""
Functional test for chat scoped tag filter enforcement.
Version: 0.240.029
Implemented in: 0.240.029

This test ensures that hybrid chat search applies the selected tag filter
consistently for personal, group, and public scopes so chat answers stay
inside the selected document tag scope.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNCTIONS_SEARCH_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "functions_search.py",
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


def get_scoped_block(content, start_marker, end_marker):
    start_index = content.index(start_marker)
    end_index = content.index(end_marker, start_index)
    return content[start_index:end_index]


def test_hybrid_search_applies_tag_filters_to_personal_group_and_public_scopes():
    """Verify scoped hybrid search branches all append the tag filter clause."""
    print("🔍 Testing scoped hybrid search tag filters...")

    content = read_file(FUNCTIONS_SEARCH_FILE)

    personal_block = get_scoped_block(
        content,
        '    elif doc_scope == "personal":',
        '    elif doc_scope == "group":',
    )
    group_block = get_scoped_block(
        content,
        '    elif doc_scope == "group":',
        '    elif doc_scope == "public":',
    )
    public_block = get_scoped_block(
        content,
        '    elif doc_scope == "public":',
        '    # Log pre-sort statistics',
    )

    required_scope_snippets = {
        "personal": [
            'user_filter = f"{user_base_filter} and {tags_filter_clause}" if tags_filter_clause else user_base_filter',
            'user_filter = f"{user_base_filter} and {tags_filter_clause}" if tags_filter_clause else user_base_filter.strip()',
            'filter=user_filter,',
            '"document_tags",',
        ],
        "group": [
            'group_filter = f"{group_base_filter} and {tags_filter_clause}" if tags_filter_clause else group_base_filter',
            'filter=group_filter,',
            '"document_tags",',
        ],
        "public": [
            'public_filter = f"{public_base_filter} and {tags_filter_clause}" if tags_filter_clause else public_base_filter',
            'filter=public_filter,',
            '"document_tags",',
        ],
    }

    scoped_blocks = {
        "personal": personal_block,
        "group": group_block,
        "public": public_block,
    }

    for scope_name, snippets in required_scope_snippets.items():
        missing = [snippet for snippet in snippets if snippet not in scoped_blocks[scope_name]]
        assert not missing, f"Missing {scope_name} scoped tag filter snippets: {missing}"

    print("✅ Scoped hybrid search tag filters passed")
    return True


def test_config_version_is_bumped_for_chat_scope_tag_filter_fix():
    """Verify config version was bumped for the scoped chat tag filter fix."""
    print("🔍 Testing config version bump...")

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.240.029"' in config_content, "Expected config.py version 0.240.029"

    print("✅ Config version bump passed")
    return True


if __name__ == "__main__":
    tests = [
        test_hybrid_search_applies_tag_filters_to_personal_group_and_public_scopes,
        test_config_version_is_bumped_for_chat_scope_tag_filter_fix,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)