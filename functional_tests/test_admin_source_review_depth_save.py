# test_admin_source_review_depth_save.py
#!/usr/bin/env python3
"""
Functional test for Admin Settings Source Traversal Depth save behavior.
Version: 0.241.079
Implemented in: 0.241.078

This test ensures that the Admin Settings form contains only one
source_review_max_depth field so saving Source Traversal Depth 2 is not
overridden by an unrelated duplicate field earlier in the form.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_TEMPLATE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "templates",
    "admin_settings.html",
)


def read_admin_template():
    """Read the Admin Settings template for static regression checks."""
    with open(ADMIN_TEMPLATE, "r", encoding="utf-8") as template_file:
        return template_file.read()


def test_source_review_depth_has_single_form_field():
    """Verify Source Traversal Depth is posted by one Admin Settings field."""
    print("Testing Source Traversal Depth form field uniqueness...")
    template_content = read_admin_template()

    depth_field_name_count = template_content.count('name="source_review_max_depth"')
    assert depth_field_name_count == 1, (
        f"Expected exactly one source_review_max_depth form field, found {depth_field_name_count}."
    )

    latest_features_start = template_content.index('id="support_latest_features_settings"')
    external_links_start = template_content.index('id="external-links-section"')
    latest_features_section = template_content[latest_features_start:external_links_start]

    assert 'name="source_review_max_depth"' not in latest_features_section, (
        "Latest Features visibility controls must not post source_review_max_depth."
    )
    assert 'name="support_latest_feature_{{ feature.id }}"' in latest_features_section, (
        "Latest Features visibility controls should post support_latest_feature_<id> checkbox fields."
    )

    print("Source Traversal Depth form field uniqueness verified.")
    return True


def main():
    """Run all regression checks."""
    tests = [test_source_review_depth_has_single_form_field]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())